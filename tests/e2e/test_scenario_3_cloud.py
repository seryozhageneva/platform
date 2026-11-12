"""Задача 29: лекция берётся из облака — Яндекс Диска преподавателя (ADR 0036).

Путь целиком: преподаватель сохраняет подключение «cloud» через API → запускает сценарий 3
с путём к лекции на Диске → блок «Источник: файл из облака» берёт токен из подключения,
вызывает MCP-сервер облака → файл лекции сохраняется в файлы преподавателя → «документ →
текст» читает его → конспект появляется в кабинете преподавателя.

Диск — подделка без сети, сервер — в том же процессе; модель — фейковая.
"""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
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
from backend.triggers.mcp_blocks import mcp_connector
from backend.triggers.worker import run_manual
from mcp_servers.cloud.server import build_server
from mcp_servers.cloud.testing import TOKEN, FakeDisk
from mcp_servers.cloud.yandex_disk import YandexDisk

API = "/api/v1"
SCENARIO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/cloud-lecture-demo.json"
LECTURE = "disk:/Лекции/дроби.docx"
SUMMARY = {"summary": "Тема лекции — дроби.", "key_concepts": ["дробь"]}


def _pipeline() -> dict:
    """Сценарий 3 из облака до конспекта в кабинете: задачи проверяет test_lecture_materials."""
    pipeline = json.loads(SCENARIO.read_text(encoding="utf-8"))
    kept = {"start", "get_file", "extract", "summarize", "save_summary"}
    pipeline["nodes"] = [node for node in pipeline["nodes"] if node["id"] in kept]
    pipeline["transitions"] = [
        move for move in pipeline["transitions"] if move["from"] in kept and move["to"] in kept
    ]
    return pipeline


def _fake_tools(connections: ConnectionRepository, disk: FakeDisk):
    """Как `connection_tools`, только сервер — в том же процессе и ходит в подделку Диска."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(disk))

    async def tools_for(owner_id, server):
        found = await connections.credentials(owner_id, ConnectionKind(server))
        assert found is not None, "подключение должно браться из базы"
        return McpToolClient({server: build_server(lambda: YandexDisk(found.token, http))})

    return tools_for


def _run(sessions, teacher, disk: FakeDisk, path: str):
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    registry = load_registry(BUILTIN_BLOCKS, {"mcp": mcp_connector(_fake_tools(connections, disk))})
    assert registry.problems == []
    llm = FakeLLM([SUMMARY])
    assembly = Assembly(sessions, registry, llm, connections=connections)
    jobs: list[UUID] = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    client = TestClient(
        create_app(assembly, enqueue=enqueue), headers={"Origin": "http://testserver"}
    )
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client.cookies.set(SESSION_COOKIE, session)

    saved = client.put(f"{API}/connections/cloud", json={"token": TOKEN})
    assert saved.status_code == 200, saved.text
    pipeline = client.post(f"{API}/pipelines", json=_pipeline())
    assert pipeline.status_code == 201, pipeline.text
    launched = client.post(
        f"{API}/pipelines/{pipeline.json()['id']}/runs",
        json={"params": {"lecture_path": path}},
    )
    assert launched.status_code == 201, launched.text
    asyncio.run(run_manual(assembly, jobs[0]))
    state = asyncio.run(assembly.runs.load(launched.json()["id"]))
    assert state is not None
    return client, state, llm


def test_lecture_from_cloud_becomes_summary_in_cabinet(sessions, teacher, sample_docx):
    disk = FakeDisk({LECTURE: sample_docx})
    client, state, llm = _run(sessions, teacher, disk, "/Лекции/дроби.docx")
    assert state.status == "done", state

    lecture = state.ports["get_file"]["file"]
    assert (lecture["name"], lecture["kind"]) == ("дроби.docx", "document")
    assert lecture["meta"] == {"cloud_path": LECTURE}
    # Лекция с Диска — в файлах преподавателя: её можно скачать, как загруженную.
    content = client.get(f"{API}/files/{lecture['id']}/content")
    assert content.status_code == 200 and content.content == sample_docx

    assert "Начало лекции" in llm.calls[0].messages[0].content
    [result] = client.get(f"{API}/results").json()
    assert result["title"] == "Конспект лекции"
    assert result["content"] == SUMMARY


def test_missing_lecture_stops_before_text(sessions, teacher, sample_docx):
    disk = FakeDisk({LECTURE: sample_docx})
    client, state, llm = _run(sessions, teacher, disk, "/Лекции/нет такой.docx")
    assert state.status == "done", state
    assert "file" not in state.ports.get("get_file", {})
    assert "extract" not in state.ports
    assert llm.calls == []
    assert client.get(f"{API}/results").json() == []
