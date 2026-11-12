"""Результаты учеников преподавателя за период (ADR 0031)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.core.contracts.ports import Event
from backend.core.contracts.run import Done, RunContext


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    if context.store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")
    end = (
        Event.model_validate(inputs["event"]).occurred_at
        if "event" in inputs
        else datetime.now(UTC)
    )
    since = end - timedelta(days=config.get("period_days", 7))
    students = await context.store.find_results(since=since)
    return Done(
        outputs={"results": [student.model_dump(mode="json") for student in students]},
        outcome="ok" if students else "empty",
    )
