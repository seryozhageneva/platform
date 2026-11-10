"""Решение преподавателя проходит через настоящий блок, API и PostgreSQL."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID

import pytest
from api_fakes import launch_and_read, saved
from sqlalchemy import select
from test_lessons_api import assign, lesson_action, student_session

from backend.core.contracts.manifest import Manifest
from backend.core.contracts.run import Done
from backend.core.engine import LoadedBlock
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.tables import ApprovalRow

API = "/api/v1"
ITEMS = [
    {"id": "a", "task": {"statement": "Черновик", "number": 1, "check_method": "short_answer"}},
    {"id": "b", "task": {"statement": "На пропуск"}},
    {"id": "c", "task": {"statement": "Без правок"}},
]
GRAPH = {
    "format": 1,
    "id": "review_demo",
    "name": "Проверка материалов",
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}, {"type": "student"}]},
        {"id": "make", "type": "block", "block": "source.test_rows"},
        {
            "id": "review",
            "type": "block",
            "block": "approval.review_table",
            "config": {"editable_fields": "id, task.statement, task.check_method"},
            "inputs": {"items": "make.items"},
        },
        {
            "id": "receive",
            "type": "block",
            "block": "sink.test_rows",
            "inputs": {"items": "review.approved"},
        },
    ],
    "transitions": [
        {"from": "start", "to": "make"},
        {"from": "make", "to": "review"},
        {"from": "review", "when": "approved", "to": "receive"},
    ],
}


@pytest.fixture
def rig(client_of, sessions):
    registry = load_registry(BUILTIN_BLOCKS)
    items = deepcopy(ITEMS)
    received = []
    # Позволяет удерживать запрос после сохранения решения, пока второй запрос пытается ответить.
    entered, release = threading.Event(), threading.Event()
    release.set()

    async def make(inputs, config, context):
        return Done(outputs={"items": items})

    async def receive(inputs, config, context):
        received.append(inputs["items"])
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return Done()

    port = {
        "name": "items",
        "title": "Строки",
        "type": "Data",
        "of": "review_items",
        "list": True,
        "schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "object",
                    "properties": {
                        "check_method": {"enum": ["short_answer", "long_answer"]},
                    },
                },
            },
        },
    }
    for name, category, ports, call in (
        ("source.test_rows", "source", {"outputs": [port]}, make),
        ("sink.test_rows", "sink", {"inputs": [port]}, receive),
    ):
        manifest = Manifest.model_validate(
            {
                "id": name,
                "name": name,
                "description": "Фейковый блок для проверки подтверждения",
                "author": "test",
                "version": "0.1.0",
                "category": category,
                "runtime": {"type": "python", "entrypoint": "unused:run"},
                **ports,
            }
        )
        registry.manifests[name] = manifest
        registry.blocks[name] = LoadedBlock(manifest, call)

    async def approvals(run_id):
        async with sessions() as session:
            return list(
                await session.scalars(
                    select(ApprovalRow)
                    .where(ApprovalRow.run_id == UUID(run_id))
                    .order_by(ApprovalRow.opened_at)
                )
            )

    return client_of(registry), items, received, entered, release, approvals


def paused(client, me, graph=GRAPH):
    started = launch_and_read(client, me, saved(client, me, graph))
    assert started.status_code == 200, started.text
    run = started.json()
    assert run["status"] == "waiting", run
    [waiting] = run["waiting"]
    assert (waiting["who"], waiting["screen"]) == ("teacher", "review_table")
    return f"{API}/runs/{run['id']}", run, waiting


def answer(waiting):
    return {
        "node_id": waiting["node_id"],
        "approval_id": waiting["approval_id"],
        "response": {
            "rows": [
                {"index": 2},
                {"index": 1, "keep": False},
                {"index": 0, "values": {"/task/statement": "Исправлено"}},
            ]
        },
    }


def test_saved_pause_and_decision_pass_edited_rows(rig, me, stranger, teacher):
    client, _, received, _, _, approvals = rig
    url, run, waiting = paused(client, me)
    assert client.get(url, headers=me).json() == run
    assert client.get(url, headers=stranger).status_code == 404
    assert received == []
    [row] = asyncio.run(approvals(run["id"]))
    assert (row.node_id, row.teacher_id, row.snapshot, row.answered_at) == (
        "review",
        teacher.id,
        waiting["data"],
        None,
    )
    assert str(row.id) == waiting["approval_id"]
    body = answer(waiting)
    assert client.post(f"{url}/responses", json=body, headers=stranger).status_code == 404
    for invalid_rows in (
        [{"index": 0}, {"index": 0}, {"index": 2}],
        [{"index": 0}, {"index": 1}, {"index": 3}],
        [{"index": 0}, {"index": 1}],
        [{"index": 0, "values": {"/id": "changed"}}, {"index": 1}, {"index": 2}],
        [{"index": 0, "values": {"/new": "new"}}, {"index": 1}, {"index": 2}],
        [{"index": 0, "values": {"/task/statement": 5}}, {"index": 1}, {"index": 2}],
        [
            {"index": 0, "values": {"/task/check_method": "несуществующий"}},
            {"index": 1},
            {"index": 2},
        ],
    ):
        bad = client.post(
            f"{url}/responses",
            json={**body, "response": {"rows": invalid_rows}},
            headers=me,
        )
        assert bad.status_code == 422, bad.text
        assert client.get(url, headers=me).json() == run
    assert asyncio.run(approvals(run["id"]))[0].answered_at is None

    finished = client.post(f"{url}/responses", json=body, headers=me)
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "done"
    assert received == [
        [{**ITEMS[0], "task": {**ITEMS[0]["task"], "statement": "Исправлено"}}, ITEMS[2]]
    ]
    [closed] = asyncio.run(approvals(run["id"]))
    assert closed.outcome == "approved" and closed.answered_at is not None
    assert closed.response["rows"][-1]["values"] == {"/task/statement": "Исправлено"}
    events = client.get(f"{url}/events", headers=me).json()
    [decision] = [event["data"] for event in events if event["type"] == "approval_decided"]
    assert decision == {"outcome": "approved", "kept": 2, "changed": 1, "skipped": 1}
    assert client.post(f"{url}/responses", json=body, headers=me).status_code == 409


def test_empty_input_and_reject_all_do_not_call_receiver(rig, me):
    client, items, received, _, _, approvals = rig
    url, run, waiting = paused(client, me)
    body = answer(waiting)
    body["response"]["rows"] = [{"index": index, "keep": False} for index in range(len(items))]
    result = client.post(f"{url}/responses", headers=me, json=body)
    assert result.json()["status"] == "done"
    [decision] = asyncio.run(approvals(run["id"]))
    assert decision.outcome == "rejected"

    items.clear()
    result = launch_and_read(client, me, saved(client, me, {**GRAPH, "id": "empty_review"}))
    assert result.json()["status"] == "done"
    assert asyncio.run(approvals(result.json()["id"])) == []
    assert received == []


def test_concurrent_answer_and_new_pause_at_same_node(rig, me):
    client, _, received, entered, release, approvals = rig
    graph = deepcopy(GRAPH)
    graph["nodes"][-2]["limit"] = {"max": 2}
    graph["transitions"].append({"from": "receive", "to": "review"})
    url, run, waiting = paused(client, me, graph)
    body = answer(waiting)
    release.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, f"{url}/responses", json=body, headers=me)
        try:
            assert entered.wait(5)
            # Решение уже записано до вызова получателя, пока он ещё выполняется.
            [closed] = asyncio.run(approvals(run["id"]))
            assert closed.answered_at is not None
            assert client.post(f"{url}/responses", json=body, headers=me).status_code == 409
        finally:
            release.set()
        second_pause = first.result()
    assert second_pause.status_code == 200, second_pause.text
    [new_waiting] = second_pause.json()["waiting"]
    assert new_waiting["node_id"] == waiting["node_id"]
    assert new_waiting["approval_id"] != waiting["approval_id"]
    assert client.post(f"{url}/responses", json=body, headers=me).status_code == 409
    assert len(received) == 1
    assert (
        client.post(f"{url}/responses", json=answer(new_waiting), headers=me).json()["status"]
        == "done"
    )
    assert len(received) == 2


def test_teacher_can_continue_assigned_lesson_but_student_cannot_review(rig, me):
    client, _, received, _, _, _ = rig
    student_id, student, _ = student_session(client, me, "Сова")
    assignment = assign(client, me, saved(client, me, GRAPH), student_id, {})
    assert assignment.status_code == 201, assignment.text
    lesson_id = assignment.json()["id"]
    assert lesson_action(client, student, lesson_id, "open").json() == {
        "status": "waiting",
        "screen": None,
    }
    [summary] = client.get(f"{API}/runs", headers=me).json()
    url = f"{API}/runs/{summary['id']}"
    [waiting] = client.get(url, headers=me).json()["waiting"]
    body = answer(waiting)
    assert client.get(url, headers=student).status_code == 403
    assert client.post(f"{url}/responses", json=body, headers=student).status_code == 403
    assert (
        lesson_action(
            client,
            student,
            lesson_id,
            "responses",
            {
                "node_id": "review",
                "revision": "0",
                "response": {"action": "hint"},
            },
        ).status_code
        == 409
    )
    assert client.post(f"{url}/responses", json=body, headers=me).json()["status"] == "done"
    assert lesson_action(client, student, lesson_id, "open").json() == {
        "status": "done",
        "screen": None,
    }
    assert len(received) == 1
