"""Хранилище запусков на PostgreSQL: состояние сохраняется и читается без потерь."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.core.contracts.pipeline import load_pipeline
from backend.core.contracts.run import BlockEvent
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus, RunStore, WaitingFor
from backend.models.pipelines import PipelineRepository
from backend.models.run_store import PgRunStore
from backend.models.tables import AssignmentRow, RunRow
from backend.models.users import UserRepository

SCENARIO_1 = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "pipelines"
    / "scenario-1-training.json"
)


@pytest.fixture
def pipeline(sessions, teacher):
    return asyncio.run(PipelineRepository(sessions).create(teacher.id, load_pipeline(SCENARIO_1)))


@pytest.fixture
def student(sessions, teacher):
    return asyncio.run(UserRepository(sessions).create_student(teacher.id, name="Ученик 1"))


def paused_state(pipeline, teacher, student) -> RunState:
    """Урок стоит на паузе: ученику показана задача, одна подсказка уже выдана."""
    return RunState(
        run_id=str(uuid.uuid4()),
        pipeline_id=str(pipeline.id),
        pipeline_version=1,
        status=RunStatus.WAITING,
        params={"topic": "logarithms", "max_hints": 3},
        student_id=str(student.id),
        teacher_id=str(teacher.id),
        current=["show"],
        ports={
            "take_task": {"task": {"id": "t1", "statement": "Вычислите $\\log_2 8$."}},
            "tutor": {"hint": {"task_id": "t1", "level": 1, "text": "Чему равно $2^3$?"}},
        },
        counters={"tutor": 1},
        waiting=[
            WaitingFor(
                node_id="show",
                who="student",
                screen=ScreenType.ANSWER_FORM,
                data={"task_id": "t1", "statement": "Вычислите $\\log_2 8$.", "forms": ["text"]},
            )
        ],
    )


def test_pg_run_store_implements_the_contract_interface(sessions):
    assert isinstance(PgRunStore(sessions), RunStore)


def test_saved_state_is_loaded_back_unchanged(sessions, pipeline, teacher, student):
    state = paused_state(pipeline, teacher, student)

    async def scenario():
        await PgRunStore(sessions).save(state)
        # Новое хранилище — как после перезапуска сервера.
        assert await PgRunStore(sessions).load(state.run_id) == state

    asyncio.run(scenario())


def test_saving_again_updates_the_same_run(sessions, pipeline, teacher, student):
    state = paused_state(pipeline, teacher, student)
    finished = state.model_copy(
        update={"status": RunStatus.DONE, "current": [], "waiting": [], "counters": {"tutor": 2}}
    )

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        await store.save(finished)

        assert await store.load(state.run_id) == finished
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(RunRow)) == 1
            row = await session.get(RunRow, uuid.UUID(state.run_id))
        # Статус лежит отдельным столбцом: по нему кабинет ищет запуски.
        assert row.status == RunStatus.DONE
        assert row.updated_at >= row.created_at

    asyncio.run(scenario())


@pytest.mark.parametrize("status", list(RunStatus))
def test_every_status_from_the_contract_is_stored(sessions, pipeline, teacher, student, status):
    state = paused_state(pipeline, teacher, student).model_copy(
        update={"status": status, "error": "модель недоступна" if status == "error" else None}
    )

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        assert await store.load(state.run_id) == state

    asyncio.run(scenario())


def test_run_without_people_is_stored(sessions, pipeline):
    """Запуск по расписанию: ни ученика, ни преподавателя за ним нет."""
    state = RunState(run_id=str(uuid.uuid4()), pipeline_id=str(pipeline.id), pipeline_version=1)

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        assert await store.load(state.run_id) == state

    asyncio.run(scenario())


def test_unknown_run_is_none(sessions):
    async def scenario():
        store = PgRunStore(sessions)
        assert await store.load(str(uuid.uuid4())) is None
        assert await store.load("run-1") is None

    asyncio.run(scenario())


def test_run_stays_on_the_pipeline_version_it_started_with(sessions, pipeline, teacher, student):
    state = paused_state(pipeline, teacher, student)

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        await PipelineRepository(sessions).save_version(
            teacher.id, pipeline.id, load_pipeline(SCENARIO_1)
        )
        await store.save(state.model_copy(update={"pipeline_version": 2}))

        assert (await store.load(state.run_id)).pipeline_version == 1

    asyncio.run(scenario())


def test_run_cannot_point_to_a_missing_pipeline_version(sessions, pipeline, teacher, student):
    state = paused_state(pipeline, teacher, student).model_copy(update={"pipeline_version": 5})

    async def scenario():
        with pytest.raises(IntegrityError):
            await PgRunStore(sessions).save(state)

    asyncio.run(scenario())


def test_identifier_that_is_not_from_the_database_is_explained(sessions, pipeline):
    state = RunState(run_id="run-1", pipeline_id=str(pipeline.id), pipeline_version=1)

    async def scenario():
        with pytest.raises(ValueError, match="run_id: «run-1» — не идентификатор из базы"):
            await PgRunStore(sessions).save(state)

    asyncio.run(scenario())


def test_events_are_kept_in_order(sessions, pipeline, teacher, student):
    state = paused_state(pipeline, teacher, student)

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        await store.append_events(
            state.run_id,
            "check_exact",
            [
                BlockEvent(type="answer_checked", data={"correct": False}),
                BlockEvent(type="attempt_counted", data={"attempt": 1}),
            ],
        )
        await store.append_events(state.run_id, "tutor", [BlockEvent(type="hint_given")])
        await store.append_events(state.run_id, "tutor", [])

        journal = await store.events(state.run_id)
        assert [(event.node_id, event.type, event.data) for event in journal] == [
            ("check_exact", "answer_checked", {"correct": False}),
            ("check_exact", "attempt_counted", {"attempt": 1}),
            ("tutor", "hint_given", {}),
        ]
        assert all(event.created_at is not None for event in journal)
        assert await store.events(str(uuid.uuid4())) == []

    asyncio.run(scenario())


def test_event_data_is_stored_as_json_like_the_state(sessions, pipeline, teacher, student):
    """Дата или идентификатор в данных события не роняют запись: они становятся строками."""
    state = paused_state(pipeline, teacher, student)
    moment = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    marker = uuid.uuid4()

    async def scenario():
        store = PgRunStore(sessions)
        await store.save(state)
        await store.append_events(
            state.run_id,
            "show",
            [BlockEvent(type="answer_received", data={"at": moment, "attempt_id": marker})],
        )

        [event] = await store.events(state.run_id)
        assert event.data == {"at": "2026-10-12T09:30:00Z", "attempt_id": str(marker)}

    asyncio.run(scenario())


def test_event_needs_an_existing_run(sessions):
    async def scenario():
        with pytest.raises(IntegrityError):
            await PgRunStore(sessions).append_events(
                str(uuid.uuid4()), "tutor", [BlockEvent(type="hint_given")]
            )

    asyncio.run(scenario())


def test_one_run_per_student_and_assignment(sessions, pipeline, teacher, student):
    """Повторное открытие урока продолжает запуск, а не создаёт второй."""

    def run_row(assignment_id):
        return RunRow(
            pipeline_id=pipeline.id,
            pipeline_version=1,
            status=RunStatus.RUNNING,
            student_id=student.id,
            assignment_id=assignment_id,
            state={},
        )

    async def scenario():
        assignment = AssignmentRow(
            pipeline_id=pipeline.id, teacher_id=teacher.id, student_id=student.id
        )
        async with sessions.begin() as session:
            session.add(assignment)
        async with sessions.begin() as session:
            session.add(run_row(assignment.id))
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(run_row(assignment.id))
        # Запусков без назначения у ученика может быть сколько угодно.
        async with sessions.begin() as session:
            session.add_all([run_row(None), run_row(None)])

    asyncio.run(scenario())


def test_assignment_goes_to_a_student_or_to_a_group_not_both(sessions, pipeline, teacher):
    async def scenario():
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(AssignmentRow(pipeline_id=pipeline.id, teacher_id=teacher.id))

    asyncio.run(scenario())
