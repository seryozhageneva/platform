"""Результаты учеников через хранилище платформы на базе (ADR 0031).

Ученики, работы и подсказки выдуманные. Работы и события кладутся прямо в таблицы с нужным
временем: так видно, что отсекается по сроку.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_task_repo import make

from backend.core.contracts.interfaces import StudentResults, WorkResult
from backend.core.contracts.pipeline import load_pipeline
from backend.core.contracts.state import RunStatus
from backend.models.pipelines import PipelineRepository
from backend.models.platform_store import PgPlatformStore
from backend.models.tables import (
    EventRow,
    RunRow,
    SubmissionRow,
    SubmissionSource,
    VerdictStatus,
)
from backend.models.tasks import TaskRepository
from backend.models.users import UserRepository

SCENARIO_1 = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "pipelines"
    / "scenario-1-training.json"
)
WEEK_AGO = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)


def store_of(sessions, owner_id) -> PgPlatformStore:
    return PgPlatformStore(sessions, owner_id, run_id=uuid.uuid4(), node_id="results")


async def lesson_run(sessions, teacher_id, student_id=None) -> uuid.UUID:
    pipeline = await PipelineRepository(sessions).create(teacher_id, load_pipeline(SCENARIO_1))
    row = RunRow(
        pipeline_id=pipeline.id,
        pipeline_version=1,
        status=RunStatus.RUNNING,
        state={},
        teacher_id=teacher_id,
        student_id=student_id,
    )
    async with sessions.begin() as session:
        session.add(row)
    return row.id


async def add_work(sessions, teacher_id, student_id, run_id, *, at, task_id="task-1", **verdict):
    row = SubmissionRow(
        owner_id=teacher_id,
        student_id=student_id,
        run_id=run_id,
        node_id="show",
        task_id=task_id,
        source=SubmissionSource.PLATFORM,
        form="text",
        text="секретный ответ",
        comment="комментарий проверки",
        created_at=at,
        **verdict,
    )
    async with sessions.begin() as session:
        session.add(row)


async def add_hint(sessions, run_id, *, at, approved=True):
    async with sessions.begin() as session:
        session.add(
            EventRow(
                run_id=run_id,
                node_id="tutor",
                type="hint_checked",
                data={"task_id": "task-1", "level": 1, "approved": approved},
                created_at=at,
            )
        )


def test_results_of_own_students_with_works_and_hints(sessions, teacher):
    async def scenario():
        users = UserRepository(sessions)
        anna = await users.create_student(teacher.id, name="Анна")
        boris = await users.create_student(teacher.id, name="Борис")
        task = await make(TaskRepository(sessions), teacher.id, topic="logarithms")
        run_id = await lesson_run(sessions, teacher.id, anna.id)
        first, second = WEEK_AGO + timedelta(days=1), WEEK_AGO + timedelta(days=2)
        await add_work(
            sessions,
            teacher.id,
            anna.id,
            run_id,
            at=second,
            task_id="задача-не-из-банка",
        )
        await add_work(
            sessions,
            teacher.id,
            anna.id,
            run_id,
            at=first,
            task_id=str(task.id),
            correct=True,
            score=1.0,
            max_score=1.0,
            verdict_status=VerdictStatus.CONFIRMED,
        )
        await add_hint(sessions, run_id, at=first)
        await add_hint(sessions, run_id, at=first)
        await add_hint(sessions, run_id, at=first, approved=False)

        found = await store_of(sessions, teacher.id).find_results(since=WEEK_AGO)

        assert found == [
            StudentResults(
                student_id=str(anna.id),
                name="Анна",
                works=[
                    WorkResult(
                        task_id=str(task.id),
                        topic="logarithms",
                        source="platform",
                        submitted_at=first,
                        status="confirmed",
                        correct=True,
                        score=1.0,
                        max_score=1.0,
                    ),
                    WorkResult(
                        task_id="задача-не-из-банка",
                        source="platform",
                        submitted_at=second,
                        status="unchecked",
                    ),
                ],
                hints=2,
            ),
            # Ученик без работ тоже в списке: «ничего не решал» — тоже результат.
            StudentResults(student_id=str(boris.id), name="Борис"),
        ]

    asyncio.run(scenario())


def test_results_do_not_show_answer_text_or_comment(sessions, teacher):
    async def scenario():
        anna = await UserRepository(sessions).create_student(teacher.id, name="Анна")
        run_id = await lesson_run(sessions, teacher.id, anna.id)
        await add_work(sessions, teacher.id, anna.id, run_id, at=WEEK_AGO)

        found = await store_of(sessions, teacher.id).find_results(since=WEEK_AGO)

        dumped = found[0].model_dump_json()
        assert "секретный ответ" not in dumped
        assert "комментарий проверки" not in dumped

    asyncio.run(scenario())


def test_older_works_and_hints_are_cut_off(sessions, teacher):
    async def scenario():
        anna = await UserRepository(sessions).create_student(teacher.id, name="Анна")
        run_id = await lesson_run(sessions, teacher.id, anna.id)
        earlier = WEEK_AGO - timedelta(seconds=1)
        await add_work(sessions, teacher.id, anna.id, run_id, at=earlier)
        await add_hint(sessions, run_id, at=earlier)
        await add_work(sessions, teacher.id, anna.id, run_id, at=WEEK_AGO, task_id="new")

        found = await store_of(sessions, teacher.id).find_results(since=WEEK_AGO)

        assert [work.task_id for work in found[0].works] == ["new"]
        assert found[0].hints == 0

    asyncio.run(scenario())


def test_another_teachers_students_are_not_visible(sessions, teacher, other_teacher):
    async def scenario():
        users = UserRepository(sessions)
        mine = await users.create_student(teacher.id, name="Мой")
        foreign = await users.create_student(other_teacher.id, name="Чужой")
        foreign_run = await lesson_run(sessions, other_teacher.id, foreign.id)
        await add_work(sessions, other_teacher.id, foreign.id, foreign_run, at=WEEK_AGO)
        await add_hint(sessions, foreign_run, at=WEEK_AGO)

        found = await store_of(sessions, teacher.id).find_results(since=WEEK_AGO)

        assert found == [StudentResults(student_id=str(mine.id), name="Мой")]

    asyncio.run(scenario())


def test_teachers_trial_run_is_not_a_students_result(sessions, teacher):
    """У ручного пробного запуска ученика нет: его ответы и подсказки никому не засчитаны."""

    async def scenario():
        anna = await UserRepository(sessions).create_student(teacher.id, name="Анна")
        trial = await lesson_run(sessions, teacher.id)
        await add_work(sessions, teacher.id, None, trial, at=WEEK_AGO)
        await add_hint(sessions, trial, at=WEEK_AGO)

        found = await store_of(sessions, teacher.id).find_results(since=WEEK_AGO)

        assert found == [StudentResults(student_id=str(anna.id), name="Анна")]

    asyncio.run(scenario())


def test_teacher_without_students_gets_an_empty_list(sessions, teacher):
    found = asyncio.run(store_of(sessions, teacher.id).find_results(since=WEEK_AGO))
    assert found == []


def test_time_without_zone_is_refused(sessions, teacher):
    with pytest.raises(ValueError, match="часовым поясом"):
        asyncio.run(store_of(sessions, teacher.id).find_results(since=datetime(2026, 11, 6, 18, 0)))
