"""Гейт 1: неверный ответ, подсказка, следующая задача и завершение урока."""

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.triggers.assembly import Assembly

API = "/api/v1"
DEMO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/student-lesson-demo.json"


def _post(client, path, *, status=200, body=None):
    response = client.post(f"{API}{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


def _create_task(client, difficulty, statement, answer):
    return _post(
        client,
        "/tasks",
        status=201,
        body={
            "subject": "Математика",
            "topic": "Дроби",
            "difficulty": difficulty,
            "statement": statement,
            "check_method": "short_answer",
            "answer": answer,
        },
    )


def _answer(client, lesson_path, screen, text):
    return _post(
        client,
        f"{lesson_path}/responses",
        body={
            "node_id": screen["node_id"],
            "revision": screen["revision"],
            "response": {
                "action": "answer",
                "answer": {"task_id": screen["task_id"], "form": "formula", "text": text},
            },
        },
    )


def test_training_gives_hint_and_advances_to_next_task(sessions, teacher):
    hint = "На какое число делятся и числитель, и знаменатель?"
    llm = FakeLLM([hint, {"approved": True}])
    app = create_app(Assembly(sessions, load_registry(BUILTIN_BLOCKS), llm))
    headers = {"Origin": "http://testserver"}
    teacher_client = TestClient(app, headers=headers)
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    teacher_client.cookies.set(SESSION_COOKIE, session)

    graph = json.loads(DEMO.read_text(encoding="utf-8"))
    pipeline = _post(teacher_client, "/pipelines", status=201, body=graph)
    student = _post(teacher_client, "/students", status=201, body={"name": "Сова"})
    first = _create_task(teacher_client, 1, "Сократите дробь 4/8.", "1/2")
    second = _create_task(teacher_client, 2, "Сократите дробь 18/24.", "3/4")
    lesson = _post(
        teacher_client,
        "/assignments",
        status=201,
        body={
            "student_id": student["id"],
            "pipeline_id": pipeline["id"],
            "params": {"topic": "Дроби", "difficulty": 1, "n_tasks": 2},
        },
    )
    link = _post(teacher_client, f"/students/{student['id']}/link")

    student_client = TestClient(app, headers=headers)
    _post(student_client, "/auth/student", body={"token": link["token"]})
    student_client.headers["X-Expected-Account"] = student["id"]
    lesson_path = f"/student/lessons/{lesson['id']}"

    opened = _post(student_client, f"{lesson_path}/open")
    assert opened["status"] == "waiting"
    screen = opened["screen"]
    assert screen["task_id"] == first["id"]
    assert screen["statement"] == first["statement"]
    assert screen["hint"] is None

    retried = _answer(student_client, lesson_path, screen, "1/3")
    assert retried["status"] == "waiting"
    screen = retried["screen"]
    assert screen["task_id"] == first["id"]
    assert screen["hint"] == {"task_id": first["id"], "level": 1, "text": hint}

    advanced = _answer(student_client, lesson_path, screen, "2/4")
    assert advanced["status"] == "waiting"
    screen = advanced["screen"]
    assert screen["task_id"] == second["id"]
    assert screen["statement"] == second["statement"]
    assert screen["hint"] is None

    finished = _answer(student_client, lesson_path, screen, "3/4")
    assert finished == {"status": "done", "screen": None}
    assert _post(student_client, f"{lesson_path}/open") == finished
    assert len(llm.calls) == 2
