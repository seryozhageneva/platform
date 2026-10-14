"""Банк задач через API и выбор задачи блоком — критерий задачи 09.

«Задачи создаются и выбираются по теме и сложности»: преподаватель создаёт задачи запросами,
а блок «Источник: банк задач» в запуске берёт задачу нужной темы и сложности. Задачи
выдуманные; модель не вызывается.
"""

from typing import Any

import pytest
from api_fakes import launch, saved

from backend.core.registry import BUILTIN_BLOCKS, load_registry

API = "/api/v1"


def fields(**changes: Any) -> dict[str, Any]:
    """Выдуманная задача с кратким ответом; отличия задаются в `changes`."""
    return {
        "subject": "math",
        "topic": "logarithms",
        "difficulty": 1,
        "statement": "Вычислите $\\log_2 8$.",
        "check_method": "short_answer",
        "answer": "3",
        **changes,
    }


def created(client, headers, **changes: Any) -> dict[str, Any]:
    response = client.post(f"{API}/tasks", json=fields(**changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def ids(client, headers, **query: Any) -> set[str]:
    response = client.get(f"{API}/tasks", params=query, headers=headers)
    assert response.status_code == 200, response.text
    return {task["id"] for task in response.json()}


def test_task_is_created_and_read(client, me):
    task = created(client, me)

    assert task["status"] == "approved"
    assert task["answer"] == "3"
    response = client.get(f"{API}/tasks/{task['id']}", headers=me)
    assert response.status_code == 200
    assert response.json() == task


def test_tasks_are_found_by_topic_and_difficulty(client, me):
    easy = created(client, me)["id"]
    hard = created(client, me, difficulty=2)["id"]
    other = created(client, me, topic="derivatives")["id"]
    draft = created(client, me, status="draft", answer=None)["id"]

    assert ids(client, me, topic="logarithms", difficulty=1) == {easy, draft}
    assert ids(client, me, topic="logarithms") == {easy, hard, draft}
    assert ids(client, me, topic="logarithms", status="approved") == {easy, hard}
    assert ids(client, me, status="draft") == {draft}
    assert ids(client, me) == {easy, hard, other, draft}
    assert ids(client, me, topic="integrals") == set()


def test_spaces_around_topic_and_subject_are_trimmed(client, me):
    task = created(client, me, topic="  logarithms ", subject=" math")

    assert (task["topic"], task["subject"]) == ("logarithms", "math")
    assert ids(client, me, topic=" logarithms ") == {task["id"]}


def test_other_teachers_task_is_not_visible(client, me, stranger):
    task = created(client, me)

    assert client.get(f"{API}/tasks/{task['id']}", headers=stranger).status_code == 404
    assert ids(client, stranger) == set()
    response = client.put(f"{API}/tasks/{task['id']}", json=fields(), headers=stranger)
    assert response.status_code == 404
    assert response.json() == {"message": "задача не найдена", "problems": []}


def test_bank_needs_to_know_who_asks(client):
    assert client.get(f"{API}/tasks").status_code == 401


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"difficulty": 0}, "difficulty"),
        ({"check_method": "guess"}, "check_method"),
        ({"topic": "   "}, "topic"),
        ({"colour": "red"}, "colour"),
    ],
)
def test_bad_task_is_refused(client, me, changes, expected):
    response = client.post(f"{API}/tasks", json=fields(**changes), headers=me)

    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "запрос не соответствует формату"
    assert any(expected in problem["message"] for problem in body["problems"])


@pytest.mark.parametrize(
    ("method", "field"),
    [("short_answer", "answer"), ("code", "tests"), ("long_answer", "rubric")],
)
def test_approved_task_must_have_what_it_is_checked_by(client, me, method, field):
    task = fields(check_method=method, answer=None)

    refused = client.post(f"{API}/tasks", json=task, headers=me)
    draft = client.post(f"{API}/tasks", json={**task, "status": "draft"}, headers=me)

    assert refused.status_code == 422
    (problem,) = refused.json()["problems"]
    assert f"«{field}»" in problem["message"]
    assert draft.status_code == 201, draft.text


def test_task_is_corrected_and_draft_is_approved(client, me):
    draft = created(client, me, status="draft", answer=None)

    response = client.put(
        f"{API}/tasks/{draft['id']}", json=fields(answer="3", difficulty=2), headers=me
    )

    assert response.status_code == 200, response.text
    task = response.json()
    assert (task["id"], task["status"], task["difficulty"]) == (draft["id"], "approved", 2)
    assert task["updated_at"] >= draft["updated_at"]
    assert ids(client, me, status="approved") == {draft["id"]}


def test_block_sees_only_the_bank_of_the_runs_teacher(client, me, stranger):
    """Сборка выдаёт блоку хранилище, ограниченное преподавателем запуска."""
    mine = created(client, me)["id"]
    created(client, stranger)
    created(client, me, status="draft", answer=None)
    pipeline_id = saved(client, me, take_pipeline("source.fake_bank", {}))

    run = launch(client, me, pipeline_id).json()

    assert run["status"] == "done", run["error"]
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    (seen,) = [event["data"] for event in events if event["type"] == "tasks_seen"]
    assert seen == {"ids": [mine]}


def take_pipeline(block: str, config: dict[str, Any]) -> dict[str, Any]:
    """Пайплайн «вручную → взять задачу» с параметрами темы и сложности."""
    return {
        "format": 1,
        "id": "take_one",
        "name": "Взять одну задачу",
        "params": [
            {"name": "topic", "title": "Тема", "type": "string", "default": "logarithms"},
            {"name": "difficulty", "title": "Сложность", "type": "integer", "default": 1},
        ],
        "nodes": [
            {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
            {"id": "take_task", "type": "block", "block": block, "config": config},
        ],
        "transitions": [{"from": "start", "to": "take_task"}],
    }


def test_tasks_are_created_and_chosen_by_topic_and_difficulty(client_of, me):
    """Критерий задачи 09 на настоящем блоке из `blocks/`."""
    client = client_of(load_registry(BUILTIN_BLOCKS))
    created(client, me, topic="logarithms", difficulty=1)
    wanted = created(client, me, topic="logarithms", difficulty=2)
    created(client, me, topic="derivatives", difficulty=2)
    created(client, me, topic="logarithms", difficulty=2, status="draft", answer=None)
    config = {"topic": {"$param": "topic"}, "difficulty": {"$param": "difficulty"}}
    pipeline_id = saved(client, me, take_pipeline("source.task_bank", config))

    run = launch(client, me, pipeline_id, topic="logarithms", difficulty=2).json()
    empty = launch(client, me, pipeline_id, topic="integrals", difficulty=1).json()

    assert run["status"] == "done", run["error"]
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    (choice,) = [event for event in events if event["type"] == "task_chosen"]
    assert choice["node_id"] == "take_task"
    assert choice["data"] == {"task_id": wanted["id"], "difficulty": 2, "reason": "start"}

    assert empty["status"] == "done", empty["error"]
    events = client.get(f"{API}/runs/{empty['id']}/events", headers=me).json()
    (missing,) = [event["data"] for event in events if event["type"] == "no_tasks"]
    assert missing == {"topic": "integrals", "subject": None, "difficulty": 1}
