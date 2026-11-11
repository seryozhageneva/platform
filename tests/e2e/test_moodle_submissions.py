"""Задача 23: работы из Moodle попадают в пайплайн (ADR 0028).

Путь целиком: преподаватель сохраняет подключение через API → запускает пайплайн →
блок «Источник: работы из Moodle» берёт адрес и токен из подключения, вызывает MCP-сервер
Moodle → файлы работ сохраняются в хранилище → «документ → текст» читает документы →
результат появляется в кабинете преподавателя.

Первый тест — на подделке Moodle, без сети: сервер в том же процессе. Второй — на настоящем
тестовом Moodle в Docker и с сервером дочерней программой; он пропускается, если тестовый
Moodle не запущен (docker-compose.moodle.yml).
"""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.mcp_client.client import McpToolClient
from backend.models.auth import AuthRepository
from backend.models.connections import ConnectionRepository, SecretBox
from backend.models.tables import ConnectionKind
from backend.triggers.assembly import Assembly
from backend.triggers.mcp_blocks import connection_tools, mcp_connector
from backend.triggers.worker import run_manual
from experiments.moodle_setup import seed_test_moodle, work_files
from mcp_servers.moodle.moodle_api import MoodleApi
from mcp_servers.moodle.server import build_server
from mcp_servers.moodle.testing import SITE, TOKEN, FakeMoodle

API = "/api/v1"
PIPELINE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "docs/examples/pipelines/moodle-works-demo.json"
    ).read_text(encoding="utf-8")
)
TEST_MOODLE = "http://localhost:8080"


def _fake_tools(connections: ConnectionRepository, moodle: FakeMoodle):
    """Как `connection_tools`, только сервер — в том же процессе и ходит в подделку."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(moodle))

    async def tools_for(owner_id, server):
        found = await connections.credentials(owner_id, ConnectionKind(server))
        assert found is not None, "подключение должно браться из базы"
        return McpToolClient(
            {server: build_server(lambda: MoodleApi(found.url, found.token, http))}
        )

    return tools_for


def _run_pipeline(sessions, teacher, tools_for, *, url, token, course_id, assignment_id):
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    registry = load_registry(BUILTIN_BLOCKS, {"mcp": mcp_connector(tools_for(connections))})
    assert registry.problems == []
    assembly = Assembly(sessions, registry, FakeLLM(), connections=connections)
    jobs: list[UUID] = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    client = TestClient(
        create_app(assembly, enqueue=enqueue), headers={"Origin": "http://testserver"}
    )
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client.cookies.set(SESSION_COOKIE, session)

    saved = client.put(f"{API}/connections/moodle", json={"url": url, "token": token})
    assert saved.status_code == 200, saved.text
    pipeline = client.post(f"{API}/pipelines", json=PIPELINE)
    assert pipeline.status_code == 201, pipeline.text
    launched = client.post(
        f"{API}/pipelines/{pipeline.json()['id']}/runs",
        json={"params": {"course_id": course_id, "assignment_id": assignment_id}},
    )
    assert launched.status_code == 201, launched.text
    asyncio.run(run_manual(assembly, jobs[0]))
    state = asyncio.run(assembly.runs.load(launched.json()["id"]))
    assert state is not None and state.status == "done", state
    return client, state


def _check_delivered(client, state):
    works = state.ports["get_works"]["works"]
    assert [(work["name"], work["kind"]) for work in works] == [
        ("work1.pdf", "document"),
        ("work2.docx", "document"),
        ("solution.py", "code"),
    ]
    # Файлы работ — в файлах преподавателя: их можно скачать, как загруженные.
    code = client.get(f"{API}/files/{works[2]['id']}/content")
    assert code.status_code == 200
    assert b"return 2 * x + 3" in code.content

    [result] = client.get(f"{API}/results").json()
    assert result["title"] == "Работы из Moodle"
    items = result["content"]
    # Код до извлечения текста не доходит, поэтому в результаты цикла не собирается
    # (docs/contract.md, раздел 5): в кабинете — два документа с их текстом.
    assert [item["work"]["name"] for item in items] == ["work1.pdf", "work2.docx"]
    assert "производную" in items[0]["text"]["text"]
    assert "сумме производных" in items[1]["text"]["text"]
    return items


def test_works_from_fake_moodle_reach_pipeline(sessions, teacher):
    moodle = FakeMoodle()
    # Те же выдуманные PDF и DOCX, что кладутся в тестовый Moodle: из них извлекается текст.
    documents = work_files()
    moodle.files["1/work1.pdf"] = documents["work1.pdf"]
    moodle.files["2/work2.docx"] = documents["work2.docx"]

    def tools_for(connections):
        return _fake_tools(connections, moodle)

    client, state = _run_pipeline(
        sessions, teacher, tools_for, url=SITE, token=TOKEN, course_id=2, assignment_id=1
    )
    items = _check_delivered(client, state)
    # Чья работа — номер студента в Moodle; имён в данных нет.
    assert [item["work"]["meta"]["moodle_user_id"] for item in items] == [4, 5]
    assert "Студент" not in json.dumps(state.ports["get_works"], ensure_ascii=False)


def _test_moodle_is_running() -> bool:
    try:
        return httpx.get(f"{TEST_MOODLE}/login/index.php", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _test_moodle_is_running(), reason="тестовый Moodle не запущен")
def test_works_from_test_moodle_reach_pipeline(sessions, teacher):
    moodle = seed_test_moodle()
    client, state = _run_pipeline(
        sessions,
        teacher,
        connection_tools,
        url=moodle.url,
        token=moodle.token,
        course_id=moodle.course_id,
        assignment_id=moodle.assignment_id,
    )
    _check_delivered(client, state)
