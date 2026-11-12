import asyncio
from datetime import UTC, datetime, timedelta

from backend.core.contracts.interfaces import StudentResults, WorkResult
from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeStore
from blocks.source.platform_results import run


def test_results_are_read_from_the_event_period():
    fired = datetime(2026, 11, 13, 15, tzinfo=UTC)
    cutoff = fired - timedelta(days=7)
    recent = WorkResult(source="platform", submitted_at=cutoff, status="confirmed", correct=True)
    old = recent.model_copy(update={"submitted_at": cutoff - timedelta(seconds=1)})
    store = FakeStore(results=[StudentResults(student_id="1", name="Сова", works=[old, recent])])
    context = RunContext(run_id="run", node_id="read", pipeline_id="digest", store=store)
    event = Event(trigger=TriggerType.SCHEDULE, occurred_at=fired)
    result = asyncio.run(run({"event": event.model_dump(mode="json")}, {"period_days": 7}, context))

    assert result.outcome == "ok"
    assert result.outputs["results"] == [
        {"student_id": "1", "name": "Сова", "works": [recent.model_dump(mode="json")], "hints": 0}
    ]


def test_results_are_empty_without_students():
    context = RunContext(run_id="run", node_id="read", pipeline_id="digest", store=FakeStore())
    result = asyncio.run(run({}, {}, context))
    assert result.outcome == "empty"
    assert result.outputs == {"results": []}
