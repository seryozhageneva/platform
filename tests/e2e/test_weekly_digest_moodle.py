"""Недельная сводка сама заглядывает в журнал Moodle (задача 28, ADR 0035).

Такт планировщика → очередь → результаты учеников → агент ИИ-обработки вызывает
`moodle.get_course_grades` с подключением преподавателя → сводка в кабинете.
"""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from arq.connections import RedisSettings
from arq.worker import Worker
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
from backend.triggers import worker as worker_module
from backend.triggers.assembly import Assembly
from backend.triggers.mcp_blocks import connection_tools
from backend.triggers.queue import serialize_job
from backend.triggers.worker import WorkerSettings
from experiments.moodle_setup import seed_test_moodle
from mcp_servers.moodle.moodle_api import MoodleApi
from mcp_servers.moodle.server import build_server
from mcp_servers.moodle.testing import SITE, TOKEN, FakeMoodle

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "docs/examples/pipelines/weekly-digest-moodle-demo.json"
)
TEST_MOODLE = "http://localhost:8080"
FRIDAY = datetime(2026, 11, 13, 15, tzinfo=UTC)
CALL = {"action": "call_tool", "tool": "moodle.get_course_grades", "arguments": {}}
DIGEST = {"summary": "По журналу Moodle у студента 4 оценка 9 из 10."}


def _fake_tools(moodle: FakeMoodle, connections: ConnectionRepository):
    """Сервер Moodle в том же процессе ходит в подделку; адрес и токен — из подключения."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(moodle))

    async def tools_for(owner_id, server):
        found = await connections.credentials(owner_id, ConnectionKind(server))
        assert found is not None, "подключение должно браться из базы"
        return McpToolClient(
            {server: build_server(lambda: MoodleApi(found.url, found.token, http))}
        )

    return tools_for


def _run_digest(sessions, teacher, monkeypatch, make_tools, *, url, token, course_id):
    """Включает расписание сводки, проводит один такт и возвращает модель, клиент и итог."""
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    llm = FakeLLM([CALL, {"action": "finish", "result": DIGEST}])
    assembly = Assembly(
        sessions,
        load_registry(BUILTIN_BLOCKS),
        llm,
        connections=connections,
        moodle_tools=make_tools(connections),
    )
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client = TestClient(create_app(assembly), headers={"Origin": "http://testserver"})
    client.cookies.set(SESSION_COOKIE, session)
    saved = client.put("/api/v1/connections/moodle", json={"url": url, "token": token})
    assert saved.status_code == 200, saved.text
    pipeline = client.post("/api/v1/pipelines", json=json.loads(EXAMPLE.read_text("utf-8")))
    assert pipeline.status_code == 201, pipeline.text
    enabled = client.put(
        f"/api/v1/pipelines/{pipeline.json()['id']}/schedule",
        json={"enabled": True, "expected_version": 1, "params": {"course_id": course_id}},
    )
    assert enabled.status_code == 200, enabled.text
    monkeypatch.setattr(worker_module, "datetime", Mock(now=Mock(return_value=FRIDAY)))

    async def run_worker():
        [tick] = [job for job in WorkerSettings.cron_jobs if job.name.endswith("check_schedules")]
        worker = Worker(
            WorkerSettings.functions,
            cron_jobs=[replace(tick, run_at_startup=True)],
            queue_name=f"platform:test:{uuid4()}",
            redis_settings=RedisSettings(host="127.0.0.1"),
            ctx={"assembly": assembly},
            job_serializer=serialize_job,
            job_deserializer=json.loads,
            burst=True,
            handle_signals=False,
            poll_delay=0.01,
            retry_jobs=False,
            keep_result=0,
        )
        try:
            # Такт планировщика и сам запуск. На тестовом Moodle запуск идёт несколько
            # секунд, и такт может сработать ещё раз; та же минута второго запуска не даёт —
            # это проверяет единственный результат ниже.
            assert await worker.run_check() >= 2
        finally:
            await worker.close()

    asyncio.run(run_worker())
    [result] = client.get("/api/v1/results").json()
    return llm, client, result


def test_digest_reads_the_fake_moodle_journal(sessions, teacher, monkeypatch):
    moodle = FakeMoodle(max_grade=10)
    moodle.journal = {4: 9}
    llm, client, result = _run_digest(
        sessions,
        teacher,
        monkeypatch,
        lambda connections: _fake_tools(moodle, connections),
        url=SITE,
        token=TOKEN,
        course_id=2,
    )
    assert result["title"] == "Сводка за неделю"
    assert result["content"] == DIGEST

    # Агент видел журнал: оценка студента 4 пришла к модели из Moodle, имени в ней нет.
    first, second = llm.calls
    assert "moodle.get_course_grades" in first.messages[0].content
    journal = second.messages[-1].content
    assert '"user_id": 4' in journal
    assert '"grade": 9.0' in journal
    asked = [r for r in moodle.requests if b"mod_assign_get_grades" in r.content]
    assert len(asked) == 1

    path = f"/api/v1/runs/{result['run_id']}"
    assert client.get(path).json()["status"] == "done"
    events = client.get(f"{path}/events").json()
    [called] = [event for event in events if event["type"] == "tool_called"]
    assert called["node_id"] == "digest"
    assert called["data"] == {
        "tool": "moodle.get_course_grades",
        "arguments": {"course_id": 2},
        "ok": True,
    }


def _test_moodle_is_running() -> bool:
    try:
        return httpx.get(f"{TEST_MOODLE}/login/index.php", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _test_moodle_is_running(), reason="тестовый Moodle не запущен")
def test_digest_reads_the_test_moodle_journal(sessions, teacher, monkeypatch):
    moodle = seed_test_moodle()

    async def grade_someone() -> int:
        async with httpx.AsyncClient(trust_env=False) as http:
            api = MoodleApi(moodle.url, moodle.token, http)
            [first, *_] = await api.submission_list(moodle.course_id, moodle.assignment_id)
            await api.save_grade(
                moodle.course_id,
                moodle.assignment_id,
                first["user_id"],
                score=7,
                max_score=10,
                comment="Оценка для проверки журнала.",
            )
            return first["user_id"]

    user_id = asyncio.run(grade_someone())
    llm, client, result = _run_digest(
        sessions,
        teacher,
        monkeypatch,
        connection_tools,
        url=moodle.url,
        token=moodle.token,
        course_id=moodle.course_id,
    )
    assert result["content"] == DIGEST
    journal = llm.calls[1].messages[-1].content
    assert f'"user_id": {user_id}' in journal
    assert "Ответ инструмента moodle.get_course_grades" in journal
    assert '"error"' not in journal
