"""Гейт 2, сценарий 2: работы из Moodle проверены, преподаватель подтвердил таблицу.

Путь: работы приходят из подделки Moodle через MCP-сервер → документ превращается в текст
и проверяется по рубрике, код — тестами в песочнице → модель пишет комментарий →
преподаватель через API правит комментарий, одну работу пропускает, остальное подтверждает.

Пайплайн — пример `scenario-2-grading.json` с двумя отличиями. Запуск вручную, потому что
запуск по событию Moodle и по расписанию появится в задачах 25 и 27. Последний цикл
«оценка в Moodle и письмо студенту» отрезан: его блоки — задачи 26 и 27. Модель фейковая,
песочница работает в том же процессе, а контейнер с программой заменён подделкой.
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
from backend.triggers.http_blocks import http_connector
from backend.triggers.mcp_blocks import connection_tools, mcp_connector
from backend.triggers.worker import run_manual
from experiments.moodle_setup import seed_test_moodle, work_files
from mcp_servers.moodle.moodle_api import MoodleApi
from mcp_servers.moodle.server import build_server
from mcp_servers.moodle.testing import SITE, TOKEN, FakeMoodle
from services.sandbox import app as sandbox
from services.sandbox.runner import Execution

API = "/api/v1"
TEST_MOODLE = "http://localhost:8080"
SCENARIO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/scenario-2-grading.json"
CUT = {"each_approved"}
GRADES = [
    {"score": 2, "max_score": 2, "comment": "Оба критерия выполнены."},
    {"score": 1, "max_score": 2, "comment": "Нет вывода формулы."},
]
COMMENTS = [
    {"text": "Хорошая работа."},
    {"text": "Допишите вывод формулы."},
    {"text": "Программа проходит тесты."},
]


def _pipeline() -> dict:
    pipeline = json.loads(SCENARIO.read_text(encoding="utf-8"))
    start = next(node for node in pipeline["nodes"] if node["type"] == "trigger")
    start["launches"] = [{"type": "manual"}]
    pipeline["nodes"] = [node for node in pipeline["nodes"] if node["id"] not in CUT]
    pipeline["transitions"] = [
        move
        for move in pipeline["transitions"]
        if move["from"] not in CUT and move["to"] not in CUT
    ]
    return pipeline


def _fake_tools(moodle: FakeMoodle, connections: ConnectionRepository):
    """Сервер Moodle — в том же процессе и ходит в подделку, адрес и токен — из подключения."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(moodle))

    async def tools_for(owner_id, server):
        found = await connections.credentials(owner_id, ConnectionKind(server))
        assert found is not None, "подключение должно браться из базы"
        return McpToolClient(
            {server: build_server(lambda: MoodleApi(found.url, found.token, http))}
        )

    return tools_for


def _post(client, path, body, status=200):
    response = client.post(f"{API}{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


def _grade_and_approve(
    sessions, teacher, monkeypatch, tools_for, *, url, token, course_id, assignment_id
):
    """Проводит сценарий 2 до конца и возвращает подтверждённые строки таблицы."""
    programs: list[str] = []

    async def execute(code, stdin, *, seconds, memory_mb):
        programs.append(code)
        assert stdin == "1\n"
        return Execution(stdout=b"5\n" if "2 * x + 3" in code else b"\n")

    monkeypatch.setattr(sandbox, "execute", execute)
    sandbox_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=sandbox.create_app()))
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    registry = load_registry(
        BUILTIN_BLOCKS,
        {"mcp": mcp_connector(tools_for(connections)), "http": http_connector(sandbox_http)},
    )
    assert registry.problems == []
    llm = FakeLLM([GRADES[0], COMMENTS[0], GRADES[1], COMMENTS[1], COMMENTS[2]])
    assembly = Assembly(sessions, registry, llm, connections=connections)
    jobs: list[UUID] = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    client = TestClient(
        create_app(assembly, enqueue=enqueue), headers={"Origin": "http://testserver"}
    )
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client.cookies.set(SESSION_COOKIE, session)

    response = client.put(f"{API}/connections/moodle", json={"url": url, "token": token})
    assert response.status_code == 200, response.text
    # Одна задача несёт и рубрику для текстовых работ, и тесты для программ.
    task = _post(
        client,
        "/tasks",
        {
            "subject": "информатика",
            "topic": "функции",
            "difficulty": 1,
            "statement": "Опишите производную и напишите функцию f(x) = 2x + 3.",
            "check_method": "code",
            "tests": json.dumps([{"stdin": "1\n", "stdout": "5\n"}]),
            "rubric": "1 балл за определение производной, 1 балл за вывод формулы.",
        },
        status=201,
    )
    pipeline = _post(client, "/pipelines", _pipeline(), status=201)
    launched = _post(
        client,
        f"/pipelines/{pipeline['id']}/runs",
        {"params": {"course_id": course_id, "assignment_id": assignment_id, "task_id": task["id"]}},
        status=201,
    )
    asyncio.run(run_manual(assembly, jobs[0]))
    asyncio.run(sandbox_http.aclose())

    run = client.get(f"{API}/runs/{launched['id']}").json()
    assert run["status"] == "waiting", run
    [waiting] = run["waiting"]
    assert waiting["node_id"] == "review"

    # Таблица преподавателя: по строке на работу, вердикт и комментарий рядом с файлом.
    state = asyncio.run(assembly.runs.load(launched["id"]))
    rows = state.ports["each_work"]["results"]
    assert [row["work"]["name"] for row in rows] == ["work1.pdf", "work2.docx", "solution.py"]
    assert [(row["verdict"]["score"], row["verdict"]["max_score"]) for row in rows] == [
        (2, 2),
        (1, 2),
        (1, 1),
    ]
    # Текст оценила модель — вердикт предварительный; код проверили тесты — окончательный.
    assert [row["verdict"]["preliminary"] for row in rows] == [True, True, False]
    assert [row["comment"] for row in rows] == COMMENTS
    [program] = programs
    assert "return 2 * x + 3" in program
    # Модель проверяла тексты работ и не видела имён: чья работа — только номер в Moodle.
    rubric_prompts = [call.messages[1].content for call in llm.calls[0:3:2]]
    assert "производную" in rubric_prompts[0]
    assert "Студент" not in json.dumps(state.ports, ensure_ascii=False)

    decision = {
        "node_id": "review",
        "approval_id": waiting["approval_id"],
        "response": {
            "rows": [
                {"index": 0},
                {"index": 1, "keep": False},
                {"index": 2, "values": {"/comment/text": "Отлично, все тесты пройдены."}},
            ]
        },
    }
    finished = _post(client, f"/runs/{launched['id']}/responses", decision)
    assert finished["status"] == "done", finished

    state = asyncio.run(assembly.runs.load(launched["id"]))
    approved = state.ports["review"]["approved"]
    assert [row["work"]["name"] for row in approved] == ["work1.pdf", "solution.py"]
    assert approved[1]["comment"] == {"text": "Отлично, все тесты пройдены."}
    return approved


def test_works_from_fake_moodle_are_graded_and_approved(sessions, teacher, monkeypatch):
    moodle = FakeMoodle()
    documents = work_files()
    moodle.files["1/work1.pdf"] = documents["work1.pdf"]
    moodle.files["2/work2.docx"] = documents["work2.docx"]
    approved = _grade_and_approve(
        sessions,
        teacher,
        monkeypatch,
        lambda connections: _fake_tools(moodle, connections),
        url=SITE,
        token=TOKEN,
        course_id=2,
        assignment_id=1,
    )
    # Чья работа — номер студента в Moodle: по нему потом выставляется оценка.
    assert [row["work"]["meta"]["moodle_user_id"] for row in approved] == [4, 6]


def _test_moodle_is_running() -> bool:
    try:
        return httpx.get(f"{TEST_MOODLE}/login/index.php", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _test_moodle_is_running(), reason="тестовый Moodle не запущен")
def test_works_from_test_moodle_are_graded_and_approved(sessions, teacher, monkeypatch):
    moodle = seed_test_moodle()
    _grade_and_approve(
        sessions,
        teacher,
        monkeypatch,
        connection_tools,
        url=moodle.url,
        token=moodle.token,
        course_id=moodle.course_id,
        assignment_id=moodle.assignment_id,
    )
