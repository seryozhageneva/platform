"""От ответа в кабинете до вердикта, записанного рядом с нужной попыткой."""

import asyncio
import json
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.triggers.assembly import Assembly
from backend.triggers.http_blocks import http_connector
from services.sandbox import app as sandbox
from services.sandbox.runner import Execution


def graph(block, form, task_id):
    return {
        "format": 1,
        "id": "grading_lesson",
        "name": "Урок с проверкой",
        "nodes": [
            {"id": "start", "type": "trigger", "launches": [{"type": "student"}]},
            {
                "id": "pick",
                "type": "block",
                "block": "source.task_bank",
                "config": {"task_id": task_id},
            },
            {
                "id": "show",
                "type": "block",
                "block": "student.show_task",
                "config": {"forms": [form], "allow_hints": False},
                "inputs": {"task": "pick.task"},
                "limit": {"max": 2},
            },
            {
                "id": "grade",
                "type": "block",
                "block": block,
                "inputs": {
                    "task": "pick.task",
                    "answer" if form == "code" else "work": "show.answer",
                },
            },
        ],
        "transitions": [
            {"from": "start", "to": "pick"},
            {"from": "pick", "when": "ok", "to": "show"},
            {"from": "show", "when": "answer", "to": "grade"},
            {"from": "grade", "when": "wrong", "to": "show"},
        ],
    }


def post(client, path, body=None, status=200):
    response = client.post(f"/api/v1{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.parametrize("form", ["text", "code"])
def test_lesson_grades_and_keeps_both_attempts(sessions, teacher, monkeypatch, form):
    async def execute(code, stdin, *, seconds, memory_mb):
        assert stdin == "2 3\n"
        return Execution(stdout=b"5\n" if "sum" in code else b"0\n")

    monkeypatch.setattr(sandbox, "execute", execute)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=sandbox.create_app()))
    registry = load_registry(BUILTIN_BLOCKS, {"http": http_connector(http)})
    llm = FakeLLM(
        [
            {"score": 0, "max_score": 1, "comment": "Не объяснено."},
            {"score": 1, "max_score": 1, "comment": "Критерий выполнен."},
        ]
        if form == "text"
        else []
    )
    assembly = Assembly(sessions, registry, llm)
    app = create_app(assembly)
    headers = {"Origin": "http://testserver"}
    with (
        TestClient(app, headers=headers) as instructor,
        TestClient(app, headers=headers) as student,
    ):
        cookie, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
        instructor.cookies.set(SESSION_COOKIE, cookie)
        learner = post(instructor, "/students", {"name": "Сова"}, status=201)
        task = post(
            instructor,
            "/tasks",
            {
                "subject": "Математика",
                "topic": "Сложение",
                "difficulty": 1,
                "statement": "Сложите два числа.",
                **(
                    {
                        "check_method": "code",
                        "tests": json.dumps([{"stdin": "2 3\n", "stdout": "5\n"}]),
                    }
                    if form == "code"
                    else {
                        "check_method": "long_answer",
                        "rubric": "1 балл за объяснение сложения.",
                    }
                ),
            },
            status=201,
        )
        block = "check.code_tests" if form == "code" else "check.rubric"
        pipeline = post(instructor, "/pipelines", graph(block, form, task["id"]), status=201)
        lesson = post(
            instructor,
            "/assignments",
            {
                "student_id": learner["id"],
                "pipeline_id": pipeline["id"],
            },
            status=201,
        )
        link = post(instructor, f"/students/{learner['id']}/link")
        post(student, "/auth/student", {"token": link["token"]})
        student.headers["X-Expected-Account"] = learner["id"]
        path = f"/student/lessons/{lesson['id']}"
        state = post(student, f"{path}/open")
        # В текстовом уроке модель оценила один и тот же ответ по-разному.
        attempts = (
            ["print(0)", "print(sum(map(int, input().split())))"]
            if form == "code"
            else ["Считаем на пальцах.", "Считаем на пальцах."]
        )
        for text in attempts:
            assert state["status"] == "waiting"
            screen = state["screen"]
            assert screen["forms"] == [form]
            state = post(
                student,
                f"{path}/responses",
                {
                    "node_id": screen["node_id"],
                    "revision": screen["revision"],
                    "response": {
                        "action": "answer",
                        "answer": {"task_id": task["id"], "form": form, "text": text},
                    },
                },
            )
        assert state["status"] == "done"
        [saved] = instructor.get("/api/v1/runs").json()
    asyncio.run(http.aclose())
    rows = asyncio.run(assembly.submissions.for_run(teacher.id, UUID(saved["id"])))
    assert [row.text for row in rows] == attempts
    assert [row.score for row in rows] == [0, 1]
    assert [row.max_score for row in rows] == [1, 1]
    status = "confirmed" if form == "code" else "preliminary"
    assert [row.verdict_status for row in rows] == [status, status]
