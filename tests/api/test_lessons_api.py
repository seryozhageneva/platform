"""Индивидуальный урок через API на настоящих блоках и фейковой модели."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest
from api_fakes import saved
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.state import RunStatus
from backend.core.contracts.testing import FakeLLM
from backend.core.engine import Engine
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.triggers.assembly import Assembly
from experiments.student_lesson_demo import HINT

API = "/api/v1"
LESSONS = f"{API}/student/lessons"
DEMO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/student-lesson-demo.json"


@pytest.fixture
def assembly(sessions):
    return Assembly(sessions, load_registry(BUILTIN_BLOCKS), FakeLLM([HINT, {"approved": True}]))


@pytest.fixture
def client(assembly):
    return TestClient(create_app(assembly), headers={"Origin": "http://testserver"})


def student_session(client, teacher_headers, name):
    created = client.post(f"{API}/students", json={"name": name}, headers=teacher_headers)
    assert created.status_code == 201, created.text
    student_id = created.json()["id"]
    issued = client.post(f"{API}/students/{student_id}/link", headers=teacher_headers)
    assert issued.status_code == 200, issued.text
    signed_in = client.post(f"{API}/auth/student", json={"token": issued.json()["token"]})
    assert signed_in.status_code == 200, signed_in.text
    return (
        student_id,
        {
            "Cookie": f"{SESSION_COOKIE}={signed_in.cookies[SESSION_COOKIE]}",
            "X-Expected-Account": student_id,
        },
        issued.json()["token"],
    )


def assign(client, headers, pipeline_id, student_id, params):
    return client.post(
        f"{API}/assignments",
        json={"student_id": student_id, "pipeline_id": pipeline_id, "params": params},
        headers=headers,
    )


@pytest.fixture
def assigned(client, me):
    student_id, headers, link = student_session(client, me, "Сова")
    graph = json.loads(DEMO.read_text())
    pipeline_id = saved(client, me, graph)
    task = client.post(
        f"{API}/tasks",
        headers=me,
        json={
            "subject": "Математика",
            "topic": "Дроби",
            "difficulty": 1,
            "statement": "Сократите дробь 4/8.",
            "check_method": "short_answer",
            "answer": "1/2",
            "solution": "Секретное решение для теста.",
        },
    )
    assert task.status_code == 201, task.text
    created = assign(client, me, pipeline_id, student_id, {"topic": "Дроби"})
    assert created.status_code == 201, created.text
    return student_id, headers, created.json()["id"], pipeline_id, graph, link


def lesson_action(client, headers, lesson_id, action, body=None):
    return client.post(f"{LESSONS}/{lesson_id}/{action}", headers=headers, json=body)


def on_screen(screen, response):
    return {"node_id": screen["node_id"], "revision": screen["revision"], "response": response}


def test_assignment_requires_owned_student_and_runnable_pipeline(client, me, stranger, assigned):
    student_id, _, _, pipeline_id, graph, _ = assigned
    foreign_id, _, _ = student_session(client, stranger, "Лис")
    foreign_pipeline = saved(client, stranger, graph)
    assert assign(client, me, pipeline_id, foreign_id, {"topic": "Дроби"}).status_code == 404
    assert assign(client, me, foreign_pipeline, student_id, {"topic": "Дроби"}).status_code == 404
    for params in ({}, {"topic": "Дроби", "n_tasks": "один"}):
        invalid = assign(client, me, pipeline_id, student_id, params)
        assert invalid.status_code == 422
        assert invalid.json()["problems"][0]["code"] == "bad_param"
    graph["nodes"][0]["launches"] = [{"type": "manual"}]
    manual_id = saved(client, me, graph)
    invalid = assign(client, me, manual_id, student_id, {"topic": "Дроби"})
    assert invalid.status_code == 422
    assert invalid.json()["problems"][0]["code"] == "launch_not_allowed"


def test_student_can_resume_ask_and_finish(client, me, assigned, assembly, teacher):
    student_id, headers, lesson_id, pipeline_id, graph, link = assigned
    assert client.get(LESSONS, headers=headers).json() == [{"id": lesson_id, "name": graph["name"]}]
    opened = lesson_action(client, headers, lesson_id, "open")
    assert opened.status_code == 200, opened.text
    assert set(opened.json()) == {"status", "screen"}
    screen = opened.json()["screen"]
    assert set(screen) == {
        "node_id",
        "revision",
        "task_id",
        "statement",
        "forms",
        "can_ask_hint",
        "hint",
    }
    assert "Секретное решение" not in opened.text and "1/2" not in opened.text

    graph["nodes"][0]["launches"] = [{"type": "manual"}]
    updated = client.put(f"{API}/pipelines/{pipeline_id}", headers=me, json=graph)
    assert updated.status_code == 200, updated.text
    # Повторный вход по той же ссылке создаёт сеанс, но урок уже начат.
    signed_in = client.post(f"{API}/auth/student", json={"token": link})
    assert signed_in.status_code == 200
    headers = {**headers, "Cookie": f"{SESSION_COOKIE}={signed_in.cookies[SESSION_COOKIE]}"}
    assert lesson_action(client, headers, lesson_id, "open").json() == opened.json()

    hint_request = on_screen(screen, {"action": "hint"})
    hinted = lesson_action(client, headers, lesson_id, "responses", hint_request)
    assert hinted.status_code == 200, hinted.text
    current = hinted.json()["screen"]
    assert current["hint"]["text"] == HINT
    assert current["node_id"] == screen["node_id"]
    assert current["revision"] != screen["revision"]
    assert lesson_action(client, headers, lesson_id, "responses", hint_request).status_code == 409
    assert lesson_action(client, headers, lesson_id, "open").json() == hinted.json()

    answer = on_screen(
        current,
        {
            "action": "answer",
            "answer": {"task_id": current["task_id"], "form": "formula", "text": "2/4"},
        },
    )
    finished = lesson_action(client, headers, lesson_id, "responses", answer)
    assert finished.json() == {"status": "done", "screen": None}
    assert lesson_action(client, headers, lesson_id, "open").json() == finished.json()
    assert lesson_action(client, headers, lesson_id, "responses", answer).status_code == 409

    run_id, _ = asyncio.run(assembly.assignments.run_for(UUID(lesson_id), UUID(student_id)))
    run = asyncio.run(assembly.runs.load(str(run_id)))
    assert run.pipeline_version == 1
    [submission] = asyncio.run(assembly.submissions.for_run(teacher.id, run_id))
    assert str(submission.student_id) == student_id
    assert submission.text == "2/4"
    assert (
        client.post(
            f"{API}/runs/{run_id}/responses",
            headers=me,
            json={"node_id": answer["node_id"], "response": answer["response"]},
        ).status_code
        == 403
    )


def test_lesson_access_and_busy_lock(client, me, assigned, assembly):
    _, headers, lesson_id, _, _, _ = assigned
    _, other, _ = student_session(client, me, "Лис")
    assert client.get(LESSONS, headers=other).json() == []
    assert lesson_action(client, other, lesson_id, "open").status_code == 404
    teacher_headers = {**me, "X-Expected-Account": headers["X-Expected-Account"]}
    assert lesson_action(client, teacher_headers, lesson_id, "open").status_code == 403
    swapped = {**headers, "X-Expected-Account": other["X-Expected-Account"]}
    assert lesson_action(client, swapped, lesson_id, "open").status_code == 409

    async def blocked():
        async with assembly.assignments.lock(UUID(lesson_id)):
            result = await asyncio.to_thread(lesson_action, client, headers, lesson_id, "open")
            assert result.status_code == 409, result.text

    asyncio.run(blocked())
    opened = lesson_action(client, headers, lesson_id, "open")
    screen = opened.json()["screen"]
    hint = on_screen(screen, {"action": "hint"})
    assert lesson_action(client, other, lesson_id, "responses", hint).status_code == 404

    run_id, _ = asyncio.run(
        assembly.assignments.run_for(UUID(lesson_id), UUID(headers["X-Expected-Account"]))
    )
    state = asyncio.run(assembly.runs.load(str(run_id)))
    state.waiting[0].who = "teacher"
    asyncio.run(assembly.runs.save(state))
    hidden = lesson_action(client, headers, lesson_id, "open")
    assert hidden.json() == {"status": "waiting", "screen": None}
    _, revision = asyncio.run(
        assembly.assignments.run_for(UUID(lesson_id), UUID(headers["X-Expected-Account"]))
    )
    hint["revision"] = revision
    assert lesson_action(client, headers, lesson_id, "responses", hint).status_code == 409


def test_open_recovers_start_interrupted_after_first_save(client, assigned, assembly, monkeypatch):
    student_id, headers, lesson_id, _, _, _ = assigned

    async def interrupt(*_args):
        raise RuntimeError("выдуманное прерывание сервера")

    with monkeypatch.context() as patch:
        patch.setattr(Engine, "_advance", interrupt)
        with pytest.raises(RuntimeError, match="выдуманное прерывание сервера"):
            lesson_action(client, headers, lesson_id, "open")

    async def saved_run():
        run_id, _ = await assembly.assignments.run_for(UUID(lesson_id), UUID(student_id))
        return await assembly.runs.load(str(run_id))

    before = asyncio.run(saved_run())
    assert before.status is RunStatus.RUNNING
    resumed = lesson_action(client, headers, lesson_id, "open")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["screen"]["statement"] == "Сократите дробь 4/8."
    after = asyncio.run(saved_run())
    assert after.run_id == before.run_id
    assert after.status is RunStatus.WAITING
