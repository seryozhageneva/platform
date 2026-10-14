"""Ответ на паузе через API — критерий задачи 10 на настоящих блоках из `blocks/`.

Урок из двух задач: «взять задачу» из банка и «показать задачу и принять ответ». Запуск
встаёт на паузу на показе задачи и после ответа продолжается: берёт следующую задачу.
Пока у ученика нет кабинета, отвечает преподаватель своего запуска (ADR 0016). Задачи и
ответы выдуманные, модель не вызывается.
"""

import asyncio
import uuid
from typing import Any

import pytest
from api_fakes import launch, saved

from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.submissions import SubmissionRepository

API = "/api/v1"

LESSON: dict[str, Any] = {
    "format": 1,
    "id": "two_tasks",
    "name": "Две задачи",
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "take_task",
            "type": "block",
            "block": "source.task_bank",
            "config": {"topic": "logarithms", "difficulty": 1},
            "inputs": {"previous": "take_task.task"},
            "limit": {"max": 2},
        },
        {
            "id": "show",
            "type": "block",
            "block": "student.show_task",
            "config": {"forms": ["text", "formula"], "allow_hints": True},
            "inputs": {"task": "take_task.task"},
        },
    ],
    "transitions": [
        {"from": "start", "to": "take_task"},
        {"from": "take_task", "when": "ok", "to": "show"},
        {"from": "show", "when": "answer", "to": "take_task"},
    ],
}


@pytest.fixture
def client(client_of):
    return client_of(load_registry(BUILTIN_BLOCKS))


@pytest.fixture
def lesson(client, me) -> str:
    """Два задания в банке и сохранённый урок; возвращает идентификатор пайплайна."""
    for number in (1, 2):
        task = {
            "subject": "math",
            "topic": "logarithms",
            "difficulty": 1,
            "statement": f"Выдуманная задача {number}: найдите $\\log_2 {2**number}$.",
            "check_method": "short_answer",
            "answer": str(number),
            "solution": f"секретное решение {number}",
        }
        response = client.post(f"{API}/tasks", json=task, headers=me)
        assert response.status_code == 201, response.text
    return saved(client, me, LESSON)


def screen(run: dict[str, Any]) -> dict[str, Any]:
    """Данные экрана, на котором стоит запуск; заодно проверяет, что он ждёт на `show`."""
    assert run["status"] == "waiting", run["error"]
    [waiting] = run["waiting"]
    assert (waiting["node_id"], waiting["who"], waiting["screen"]) == (
        "show",
        "student",
        "answer_form",
    )
    return waiting["data"]


def answer(task_id: str, text: str = "3") -> dict[str, Any]:
    return {
        "node_id": "show",
        "response": {
            "action": "answer",
            "answer": {"task_id": task_id, "form": "text", "text": text},
        },
    }


def respond(client, headers, run_id: str, body: dict[str, Any]):
    return client.post(f"{API}/runs/{run_id}/responses", json=body, headers=headers)


def journal(client, headers, run_id: str) -> list[tuple[str, str]]:
    events = client.get(f"{API}/runs/{run_id}/events", headers=headers).json()
    return [(event["node_id"], event["type"]) for event in events]


def submissions(sessions, teacher, run_id: str):
    repo = SubmissionRepository(sessions)
    return asyncio.run(repo.for_run(teacher.id, uuid.UUID(run_id)))


def test_run_pauses_and_continues_after_the_answer(client, me, lesson, sessions, teacher):
    """Критерий задачи 10: запуск встаёт на паузу и продолжается после ответа."""
    started = launch(client, me, lesson)
    assert started.status_code == 201, started.text
    run = started.json()
    first = screen(run)

    # Состояние читается отдельным запросом: условие видно, ответа и решения нет.
    assert screen(client.get(f"{API}/runs/{run['id']}", headers=me).json()) == first
    assert first["statement"].startswith("Выдуманная задача")
    assert "answer" not in first and "секретное решение" not in str(first)

    after_first = respond(client, me, run["id"], answer(first["task_id"], "1"))

    assert after_first.status_code == 200, after_first.text
    second = screen(after_first.json())
    assert second["task_id"] != first["task_id"]

    after_second = respond(client, me, run["id"], answer(second["task_id"], "2"))

    assert after_second.status_code == 200, after_second.text
    finished = after_second.json()
    assert finished["status"] == "done", finished["error"]
    assert finished["waiting"] == []

    one_task = [
        ("take_task", "task_chosen"),
        ("take_task", "node_done"),
        ("show", "task_shown"),
        ("show", "node_waiting"),
        ("show", "node_resumed"),
        ("show", "answer_received"),
        ("show", "node_done"),
    ]
    assert journal(client, me, run["id"]) == [
        ("start", "run_started"),
        *one_task,
        *one_task,
        ("take_task", "limit_reached"),
        ("take_task", "run_done"),
    ]

    stored = submissions(sessions, teacher, run["id"])
    assert [(row.task_id, row.text, row.node_id) for row in stored] == [
        (first["task_id"], "1", "show"),
        (second["task_id"], "2", "show"),
    ]
    assert all(row.student_id is None and row.owner_id == teacher.id for row in stored)


def test_answer_to_another_task_is_asked_again(client, me, lesson, sessions, teacher):
    run = launch(client, me, lesson).json()
    shown = screen(run)

    again = respond(client, me, run["id"], answer("old-task"))

    assert again.status_code == 200, again.text
    assert screen(again.json()) == shown
    assert ("show", "response_refused") in journal(client, me, run["id"])
    assert submissions(sessions, teacher, run["id"]) == []


def test_answer_in_a_wrong_shape_is_refused_and_changes_nothing(client, me, lesson):
    run = launch(client, me, lesson).json()

    refused = respond(client, me, run["id"], {"node_id": "show", "response": {"action": "dance"}})

    assert refused.status_code == 422, refused.text
    assert "answer_form" in refused.json()["message"]
    assert client.get(f"{API}/runs/{run['id']}", headers=me).json() == run


def test_answer_to_a_node_that_is_not_waiting_is_a_conflict(client, me, lesson):
    run = launch(client, me, lesson).json()

    wrong_node = respond(client, me, run["id"], {**answer("x"), "node_id": "take_task"})

    assert wrong_node.status_code == 409, wrong_node.text
    assert "take_task" in wrong_node.json()["message"]


def test_finished_run_does_not_take_answers(client, me, lesson):
    run = launch(client, me, lesson).json()
    for _ in range(2):
        shown = screen(client.get(f"{API}/runs/{run['id']}", headers=me).json())
        respond(client, me, run["id"], answer(shown["task_id"]))

    late = respond(client, me, run["id"], answer("any"))

    assert late.status_code == 409, late.text


def test_other_teacher_cannot_answer(client, me, stranger, lesson):
    run = launch(client, me, lesson).json()

    response = respond(client, stranger, run["id"], answer(screen(run)["task_id"]))

    assert response.status_code == 404, response.text
    assert client.get(f"{API}/runs/{run['id']}", headers=me).json() == run


def test_unknown_field_in_the_body_is_refused(client, me, lesson):
    run = launch(client, me, lesson).json()

    response = respond(client, me, run["id"], {**answer("x"), "nodeid": "show"})

    assert response.status_code == 422, response.text


def test_run_continues_on_its_own_pipeline_version(client, me, lesson):
    """Пайплайн пересохранили во время паузы — запуск всё равно идёт по своей версии."""
    run = launch(client, me, lesson).json()
    changed = {**LESSON, "transitions": LESSON["transitions"][:2]}
    resaved = client.put(f"{API}/pipelines/{lesson}", json=changed, headers=me)
    assert resaved.status_code == 200, resaved.text

    response = respond(client, me, run["id"], answer(screen(run)["task_id"]))

    # В новой версии после ответа запуск закончился бы; в своей — берёт вторую задачу.
    assert response.status_code == 200, response.text
    assert response.json()["pipeline_version"] == 1
    screen(response.json())


def test_answer_with_a_null_character_is_asked_again(client, me, lesson, sessions, teacher):
    run = launch(client, me, lesson).json()

    again = respond(client, me, run["id"], answer(screen(run)["task_id"], "SECRET\x00tail"))

    assert again.status_code == 200, again.text
    screen(again.json())
    assert ("show", "response_refused") in journal(client, me, run["id"])
    assert submissions(sessions, teacher, run["id"]) == []


def test_failed_submission_does_not_leak_the_answer(client, me, lesson, monkeypatch):
    """Работу не удалось записать: запуск в ошибке, но текста ответа нет ни в ней, ни в журнале."""

    async def broken(*args, **kwargs):
        raise RuntimeError("ошибка базы: INSERT ... [parameters: ('SECRET-ANSWER',)]")

    monkeypatch.setattr(client.app.state.assembly.submissions, "add_answer", broken)
    run = launch(client, me, lesson).json()

    failed = respond(client, me, run["id"], answer(screen(run)["task_id"], "SECRET-ANSWER"))

    assert failed.status_code == 200, failed.text
    state = failed.json()
    assert state["status"] == "error"
    assert "RuntimeError" in state["error"]
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    assert "SECRET-ANSWER" not in str(state) + str(events)
