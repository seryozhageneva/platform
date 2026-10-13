"""Журнал вызовов модели в базе: вызов сохраняется и привязывается к запуску."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.core.contracts.pipeline import load_pipeline
from backend.core.contracts.state import RunState
from backend.models.llm_calls import LLMCallRepository
from backend.models.pipelines import PipelineRepository
from backend.models.run_store import PgRunStore
from backend.models.tables import LLMCallRow, RunRow

SCENARIO_1 = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "pipelines"
    / "scenario-1-training.json"
)
CALL = {
    "provider": "gigachat",
    "model": "GigaChat-2",
    "input_tokens": 120,
    "output_tokens": 35,
    "latency_ms": 840,
}


@pytest.fixture
def run_id(sessions, teacher) -> str:
    """Выдуманный запуск: журнал ссылается на него, а база проверяет, что он существует."""

    async def create() -> str:
        pipeline = await PipelineRepository(sessions).create(teacher.id, load_pipeline(SCENARIO_1))
        state = RunState(run_id=str(uuid.uuid4()), pipeline_id=str(pipeline.id), pipeline_version=1)
        await PgRunStore(sessions).save(state)
        return state.run_id

    return asyncio.run(create())


def all_calls(sessions) -> list[LLMCallRow]:
    async def read():
        async with sessions() as session:
            return list(await session.scalars(select(LLMCallRow).order_by(LLMCallRow.id)))

    return asyncio.run(read())


def test_call_of_a_run_is_saved(sessions, run_id):
    calls = LLMCallRepository(sessions)

    asyncio.run(calls.record(**CALL, run_id=run_id, node_id="tutor"))

    (row,) = asyncio.run(calls.for_run(run_id))
    assert (row.provider, row.model) == ("gigachat", "GigaChat-2")
    assert (row.input_tokens, row.output_tokens, row.latency_ms) == (120, 35, 840)
    assert (str(row.run_id), row.node_id) == (run_id, "tutor")
    assert row.error is None
    assert row.created_at is not None


def test_call_outside_a_run_is_saved_too(sessions):
    """Ручная проверка модели и замеры идут без запуска."""
    asyncio.run(LLMCallRepository(sessions).record(**CALL))

    (row,) = all_calls(sessions)
    assert row.run_id is None and row.node_id is None


def test_failed_call_keeps_the_kind_of_failure(sessions, run_id):
    calls = LLMCallRepository(sessions)

    asyncio.run(calls.record(**{**CALL, "output_tokens": 0}, error="timeout", run_id=run_id))

    assert asyncio.run(calls.for_run(run_id))[0].error == "timeout"


def test_calls_of_a_run_come_in_the_order_they_were_made(sessions, run_id):
    calls = LLMCallRepository(sessions)

    async def scenario():
        for node in ["tutor", "controller", "tutor"]:
            await calls.record(**CALL, run_id=run_id, node_id=node)
        await calls.record(**CALL)
        return await calls.for_run(run_id)

    assert [row.node_id for row in asyncio.run(scenario())] == ["tutor", "controller", "tutor"]


def test_unknown_run_has_no_calls(sessions):
    calls = LLMCallRepository(sessions)

    assert asyncio.run(calls.for_run(str(uuid.uuid4()))) == []
    assert asyncio.run(calls.for_run("run-1")) == []


def test_call_cannot_point_at_a_run_that_does_not_exist(sessions):
    with pytest.raises(IntegrityError):
        asyncio.run(LLMCallRepository(sessions).record(**CALL, run_id=str(uuid.uuid4())))


def test_run_id_that_is_not_from_the_database_is_explained(sessions):
    with pytest.raises(ValueError, match="run_id: «run-1» — не идентификатор из базы"):
        asyncio.run(LLMCallRepository(sessions).record(**CALL, run_id="run-1"))


def test_negative_numbers_are_rejected_by_the_database(sessions):
    calls = LLMCallRepository(sessions)

    with pytest.raises(IntegrityError):
        asyncio.run(calls.record(**{**CALL, "input_tokens": -1}))
    with pytest.raises(IntegrityError):
        asyncio.run(calls.record(**{**CALL, "latency_ms": -1}))


def test_calls_are_removed_together_with_their_run(sessions, run_id):
    calls = LLMCallRepository(sessions)

    async def scenario() -> int:
        await calls.record(**CALL, run_id=run_id)
        async with sessions.begin() as session:
            await session.execute(delete(RunRow).where(RunRow.id == uuid.UUID(run_id)))
        async with sessions() as session:
            return await session.scalar(select(func.count()).select_from(LLMCallRow))

    assert asyncio.run(scenario()) == 0
