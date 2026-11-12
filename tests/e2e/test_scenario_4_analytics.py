"""Еженедельная сводка: от такта планировщика через Redis до кабинета преподавателя."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from arq.connections import RedisSettings
from arq.worker import Worker
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.models.users import UserRepository
from backend.triggers import worker as worker_module
from backend.triggers.assembly import Assembly
from backend.triggers.queue import serialize_job
from backend.triggers.worker import WorkerSettings

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/weekly-digest-demo.json"
FRIDAY = datetime(2026, 11, 13, 15, tzinfo=UTC)
DIGEST = {"summary": "Сова пока не сдавала работы."}


def test_weekly_digest_reaches_the_teacher_cabinet(sessions, teacher, other_teacher, monkeypatch):
    llm = FakeLLM([DIGEST])
    assembly = Assembly(sessions, load_registry(BUILTIN_BLOCKS), llm)
    token, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client = TestClient(create_app(assembly), headers={"Origin": "http://testserver"})
    client.cookies.set(SESSION_COOKIE, token)
    saved = client.post("/api/v1/pipelines", json=json.loads(EXAMPLE.read_text(encoding="utf-8")))
    assert saved.status_code == 201, saved.text
    enabled = client.put(
        f"/api/v1/pipelines/{saved.json()['id']}/schedule",
        json={"enabled": True, "expected_version": 1},
    )
    assert enabled.status_code == 200, enabled.text
    monkeypatch.setattr(worker_module, "datetime", Mock(now=Mock(return_value=FRIDAY)))

    async def run_worker():
        users = UserRepository(sessions)
        await users.create_student(teacher.id, name="Сова")
        await users.create_student(other_teacher.id, name="Медведь")
        redis_settings = RedisSettings(host="127.0.0.1")
        name = f"platform:test:{uuid4()}"
        # Только проверка расписаний: опрос Moodle этому сценарию не нужен.
        [tick] = [job for job in WorkerSettings.cron_jobs if job.name.endswith("check_schedules")]
        worker = Worker(
            WorkerSettings.functions,
            cron_jobs=[replace(tick, run_at_startup=True)],
            queue_name=name,
            redis_settings=redis_settings,
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
            assert await worker.run_check() == 2  # Такт планировщика и сам запуск.
        finally:
            await worker.close()

    asyncio.run(run_worker())
    [call] = llm.calls
    assert "Сова" in call.messages[0].content
    assert "Медведь" not in call.messages[0].content

    [result] = client.get("/api/v1/results").json()
    assert result["title"] == "Сводка за неделю"
    assert result["content"] == DIGEST
    assert result["student_id"] is None
    path = f"/api/v1/runs/{result['run_id']}"
    assert client.get(path).json()["status"] == "done"
    events = client.get(f"{path}/events").json()
    assert [event["type"] for event in events[:2]] == ["run_queued", "run_started"]
    assert events[1]["data"]["trigger"] == "schedule"
