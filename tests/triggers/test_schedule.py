import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from backend.core.contracts.pipeline import load_pipeline
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.triggers.assembly import Assembly
from backend.triggers.queue import QueueUnavailable
from backend.triggers.schedule import enqueue_schedules

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/weekly-digest-demo.json"
FRIDAY = datetime(2026, 11, 13, 15, tzinfo=UTC)


def test_scheduler_checks_only_current_moscow_minute_and_claims_it_once(sessions, teacher):
    async def scenario():
        assembly = Assembly(sessions, load_registry(BUILTIN_BLOCKS))
        row = await assembly.pipelines.create(teacher.id, load_pipeline(EXAMPLE))
        jobs: list[UUID] = []

        async def enqueue(run_id: UUID) -> None:
            jobs.append(run_id)

        await enqueue_schedules(assembly, enqueue, now=FRIDAY)
        assert jobs == []
        await assembly.schedules.save(row.id, 1, enabled=True, params={})
        await enqueue_schedules(assembly, enqueue, now=FRIDAY + timedelta(minutes=1))
        assert jobs == []

        await asyncio.gather(
            enqueue_schedules(assembly, enqueue, now=FRIDAY),
            enqueue_schedules(assembly, enqueue, now=FRIDAY + timedelta(seconds=45)),
        )
        assert len(jobs) == 1
        [run] = await assembly.runs.for_teacher(teacher.id)
        assert run["id"] == jobs[0]
        assert (await assembly.schedules.get(row.id)).last_fired_at == FRIDAY

        await assembly.schedules.save(row.id, 1, enabled=False, params={})
        await enqueue_schedules(assembly, enqueue, now=FRIDAY + timedelta(weeks=1))
        assert len(jobs) == 1

    asyncio.run(scenario())


def test_redis_failure_rolls_back_run_and_minute_claim(sessions, teacher):
    async def scenario():
        assembly = Assembly(sessions, load_registry(BUILTIN_BLOCKS))
        row = await assembly.pipelines.create(teacher.id, load_pipeline(EXAMPLE))
        await assembly.schedules.save(row.id, 1, enabled=True, params={})

        async def unavailable(run_id: UUID) -> None:
            raise QueueUnavailable

        await enqueue_schedules(assembly, unavailable, now=FRIDAY)

        assert await assembly.runs.for_teacher(teacher.id) == []
        assert (await assembly.schedules.get(row.id)).last_fired_at is None

    asyncio.run(scenario())
