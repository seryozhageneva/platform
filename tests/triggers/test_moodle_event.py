"""Триггер «событие Moodle»: опрос, только новые сдачи, один запуск (ADR 0034).

Moodle — подделка за настоящим MCP-сервером в том же процессе. База — тестовая.
"""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import TriggerType
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.mcp_client.client import McpToolClient
from backend.triggers.assembly import Assembly
from backend.triggers.manual import launch_problems
from backend.triggers.mcp_blocks import mcp_connector
from backend.triggers.moodle_event import poll_moodle
from backend.triggers.queue import QueueUnavailable
from mcp_servers.moodle.testing import SUBMISSIONS, FakeMoodle, fake_server

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/moodle-works-demo.json"
NOON = datetime(2026, 11, 12, 12, tzinfo=UTC)
PARAMS = {"course_id": 2, "assignment_id": 1}


def _graph(poll_minutes: int = 5, *, bind_event: bool = True) -> Pipeline:
    graph = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    graph["nodes"][0]["launches"] = [
        {"type": "moodle_event", "settings": {"poll_minutes": poll_minutes}}
    ]
    if not bind_event:
        del graph["nodes"][1]["inputs"]
    return Pipeline.model_validate(graph)


class Setup:
    def __init__(self, sessions, moodle: FakeMoodle) -> None:
        async def tools_for(owner_id, server):
            return McpToolClient({server: fake_server(moodle)})

        registry = load_registry(BUILTIN_BLOCKS, {"mcp": mcp_connector(tools_for)})
        self.assembly = Assembly(sessions, registry, moodle_tools=tools_for)
        self.moodle = moodle
        self.jobs: list[UUID] = []

    async def enqueue(self, run_id: UUID) -> None:
        self.jobs.append(run_id)

    async def poll(self, now: datetime, enqueue=None) -> None:
        await poll_moodle(self.assembly, enqueue or self.enqueue, now=now)

    def list_calls(self) -> int:
        return sum(
            b"mod_assign_get_submissions" in request.content for request in self.moodle.requests
        )


def _event(state) -> dict:
    return state.ports["start"]["event"]


def test_new_submissions_start_one_run_and_are_not_taken_again(sessions, teacher):
    async def scenario():
        setup = Setup(sessions, FakeMoodle(copy.deepcopy(SUBMISSIONS)))
        watches = setup.assembly.moodle_watches
        row = await setup.assembly.pipelines.create(teacher.id, _graph())

        await setup.poll(NOON)
        assert setup.jobs == [] and setup.list_calls() == 0, "наблюдение ещё не включено"

        await watches.save(row.id, 1, enabled=True, params=PARAMS)
        await setup.poll(NOON)
        [run_id] = setup.jobs
        state = await setup.assembly.runs.load(str(run_id))
        event = _event(state)
        assert event["trigger"] == "moodle_event"
        # Черновик и пустая сдача не берутся; номера сдач — в событии запуска.
        assert event["payload"] == {
            "moodle_course_id": 2,
            "moodle_assignment_id": 1,
            "moodle_submission_ids": [1, 2, 3],
        }
        assert state.teacher_id == str(teacher.id)
        watch = await watches.get(row.id)
        assert (watch.last_polled_at, watch.last_error) == (NOON, None)
        assert await watches.seen_count(row.id) == 3

        # Раньше срока Moodle не опрашивается; в срок — опрашивается, но новых сдач нет.
        await setup.poll(NOON + timedelta(minutes=4, seconds=59))
        assert setup.list_calls() == 1
        await setup.poll(NOON + timedelta(minutes=5))
        assert setup.list_calls() == 2
        assert len(setup.jobs) == 1

        # Студент доработал и пересдал работу: время сдачи изменилось — это новая сдача.
        setup.moodle.submissions[1]["timemodified"] += 600
        await setup.poll(NOON + timedelta(minutes=10))
        assert len(setup.jobs) == 2
        again = await setup.assembly.runs.load(str(setup.jobs[1]))
        assert _event(again)["payload"]["moodle_submission_ids"] == [2]

        await watches.save(row.id, 1, enabled=False, params=PARAMS)
        setup.moodle.submissions[0]["timemodified"] += 600
        await setup.poll(NOON + timedelta(hours=1))
        assert len(setup.jobs) == 2

    asyncio.run(scenario())


def test_two_workers_in_the_same_minute_start_one_run(sessions, teacher):
    async def scenario():
        setup = Setup(sessions, FakeMoodle())
        row = await setup.assembly.pipelines.create(teacher.id, _graph())
        await setup.assembly.moodle_watches.save(row.id, 1, enabled=True, params=PARAMS)
        await asyncio.gather(setup.poll(NOON), setup.poll(NOON + timedelta(seconds=40)))
        assert len(setup.jobs) == 1
        assert len(await setup.assembly.runs.for_teacher(teacher.id)) == 1

    asyncio.run(scenario())


def test_queue_failure_keeps_submissions_new_for_the_next_poll(sessions, teacher):
    async def scenario():
        setup = Setup(sessions, FakeMoodle())
        row = await setup.assembly.pipelines.create(teacher.id, _graph(poll_minutes=1))
        await setup.assembly.moodle_watches.save(row.id, 1, enabled=True, params=PARAMS)

        async def unavailable(run_id: UUID) -> None:
            raise QueueUnavailable

        await setup.poll(NOON, unavailable)
        assert await setup.assembly.runs.for_teacher(teacher.id) == []
        assert await setup.assembly.moodle_watches.seen_count(row.id) == 0

        await setup.poll(NOON + timedelta(minutes=1))
        assert len(setup.jobs) == 1
        assert await setup.assembly.moodle_watches.seen_count(row.id) == 3

    asyncio.run(scenario())


def test_moodle_error_is_shown_to_teacher_and_clears_after_success(sessions, teacher):
    async def scenario():
        moodle = FakeMoodle(token="ffffffffffffffffffffffffffffffff")
        setup = Setup(sessions, moodle)
        row = await setup.assembly.pipelines.create(teacher.id, _graph(poll_minutes=1))
        await setup.assembly.moodle_watches.save(row.id, 1, enabled=True, params=PARAMS)

        await setup.poll(NOON)
        watch = await setup.assembly.moodle_watches.get(row.id)
        assert "Moodle не принял токен" in watch.last_error
        assert setup.jobs == []

        moodle.token = "0123456789abcdef0123456789abcdef"
        await setup.poll(NOON + timedelta(minutes=1))
        assert (await setup.assembly.moodle_watches.get(row.id)).last_error is None
        assert len(setup.jobs) == 1

    asyncio.run(scenario())


def test_launch_by_event_needs_bound_event_and_sane_poll_minutes(sessions, teacher):
    setup = Setup(sessions, FakeMoodle())
    check = launch_problems
    assert check(setup.assembly, _graph(), TriggerType.MOODLE_EVENT, PARAMS) == []
    [unbound] = check(setup.assembly, _graph(bind_event=False), TriggerType.MOODLE_EVENT, PARAMS)
    assert (unbound.node, unbound.code) == ("get_works", "moodle_event_not_bound")
    [too_often] = check(setup.assembly, _graph(poll_minutes=0), TriggerType.MOODLE_EVENT, PARAMS)
    assert too_often.code == "bad_poll_minutes"
    # Ручной запуск того же графа без события по-прежнему возможен — проверка только для события.
    manual = _graph(bind_event=False).model_copy(deep=True)
    manual.nodes[0].launches[0].type = TriggerType.MANUAL
    assert check(setup.assembly, manual, TriggerType.MANUAL, PARAMS) == []


def test_problem_in_graph_is_recorded_without_calling_moodle(sessions, teacher):
    async def scenario():
        setup = Setup(sessions, FakeMoodle())
        row = await setup.assembly.pipelines.create(teacher.id, _graph(bind_event=False))
        await setup.assembly.moodle_watches.save(row.id, 1, enabled=True, params=PARAMS)
        await setup.poll(NOON)
        assert setup.list_calls() == 0 and setup.jobs == []
        assert "привязать" in (await setup.assembly.moodle_watches.get(row.id)).last_error

    asyncio.run(scenario())


def test_saving_graph_without_moodle_launch_turns_watch_off(sessions, teacher):
    async def scenario():
        setup = Setup(sessions, FakeMoodle())
        pipelines = setup.assembly.pipelines
        row = await pipelines.create(teacher.id, _graph())
        await setup.assembly.moodle_watches.save(row.id, 1, enabled=True, params=PARAMS)
        manual = _graph().model_copy(deep=True)
        manual.nodes[0].launches[0].type = TriggerType.MANUAL
        await pipelines.save_version(teacher.id, row.id, manual)
        assert (await setup.assembly.moodle_watches.get(row.id)).enabled is False

    asyncio.run(scenario())
