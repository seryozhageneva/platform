"""Работы учеников в PostgreSQL (ADR 0016): запись, чтение по запуску и границы владельца.

Ответы выдуманные. Запуск для работ создаётся через хранилище запусков: без запуска в базе
работа к нему не привяжется.
"""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.core.contracts.pipeline import load_pipeline
from backend.core.contracts.ports import Answer, AnswerForm, FileKind, FileRef
from backend.core.contracts.state import RunState
from backend.models.pipelines import PipelineRepository
from backend.models.run_store import PgRunStore
from backend.models.submissions import SubmissionRepository
from backend.models.tables import SubmissionRow, SubmissionSource, VerdictStatus
from backend.models.users import UserRepository

SCENARIO_1 = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "pipelines"
    / "scenario-1-training.json"
)


@pytest.fixture
def run_id(sessions, teacher) -> uuid.UUID:
    async def scenario():
        pipeline = await PipelineRepository(sessions).create(teacher.id, load_pipeline(SCENARIO_1))
        state = RunState(
            run_id=str(uuid.uuid4()),
            pipeline_id=str(pipeline.id),
            pipeline_version=1,
            teacher_id=str(teacher.id),
        )
        await PgRunStore(sessions).save(state)
        return uuid.UUID(state.run_id)

    return asyncio.run(scenario())


PHOTO = FileRef(id="file-1", name="solution.jpg", kind=FileKind.IMAGE, media_type="image/jpeg")


def text_answer(text: str = "3", form: AnswerForm = AnswerForm.TEXT) -> Answer:
    if form is AnswerForm.PHOTO:
        return Answer(task_id="task-1", form=form, file=PHOTO)
    return Answer(task_id="task-1", form=form, text=text)


def test_answer_is_stored_and_read_by_run(sessions, teacher, run_id):
    async def scenario():
        repo = SubmissionRepository(sessions)
        student = await UserRepository(sessions).create_student(teacher.id, name="Ученик 1")
        await repo.add_answer(
            teacher.id, text_answer("3"), run_id=run_id, node_id="show", student_id=student.id
        )
        await repo.add_answer(teacher.id, text_answer("x = 2"), run_id=run_id, node_id="show")
        return student, await repo.for_run(teacher.id, run_id)

    student, rows = asyncio.run(scenario())

    assert [row.text for row in rows] == ["3", "x = 2"]
    first = rows[0]
    assert first.student_id == student.id
    assert (first.task_id, first.node_id, first.form) == ("task-1", "show", "text")
    assert first.source == SubmissionSource.PLATFORM
    # Пока работу не проверили, оценки и вердикта нет.
    assert (first.score, first.comment, first.verdict_status) == (None, None, None)
    assert rows[1].student_id is None


def test_photo_answer_keeps_only_a_link_to_the_file(sessions, teacher, run_id):
    async def scenario():
        repo = SubmissionRepository(sessions)
        answer = text_answer(form=AnswerForm.PHOTO)
        await repo.add_answer(teacher.id, answer, run_id=run_id, node_id="show")
        return await repo.for_run(teacher.id, run_id)

    [row] = asyncio.run(scenario())

    assert row.text is None
    assert FileRef.model_validate(row.file) == PHOTO


def test_other_teacher_does_not_see_the_submissions(sessions, teacher, other_teacher, run_id):
    async def scenario():
        repo = SubmissionRepository(sessions)
        await repo.add_answer(teacher.id, text_answer(), run_id=run_id, node_id="show")
        return await repo.for_run(other_teacher.id, run_id)

    assert asyncio.run(scenario()) == []


@pytest.mark.parametrize("form", list(AnswerForm))
def test_every_answer_form_is_stored(sessions, teacher, run_id, form):
    async def scenario():
        repo = SubmissionRepository(sessions)
        await repo.add_answer(teacher.id, text_answer(form=form), run_id=run_id, node_id="show")
        return await repo.for_run(teacher.id, run_id)

    [row] = asyncio.run(scenario())

    assert row.form == form.value


def store(sessions, row: SubmissionRow) -> None:
    async def scenario():
        async with sessions.begin() as session:
            session.add(row)

    asyncio.run(scenario())


@pytest.mark.parametrize("source", list(SubmissionSource))
@pytest.mark.parametrize("status", list(VerdictStatus))
def test_every_source_and_verdict_status_is_stored(sessions, teacher, source, status):
    store(
        sessions,
        SubmissionRow(owner_id=teacher.id, source=source, verdict_status=status, score=4.0),
    )


@pytest.mark.parametrize(
    "broken",
    [{"source": "email"}, {"form": "voice"}, {"verdict_status": "maybe"}],
    ids=["source", "form", "verdict_status"],
)
def test_database_rejects_impossible_values(sessions, teacher, broken):
    with pytest.raises(IntegrityError):
        store(sessions, SubmissionRow(owner_id=teacher.id, **{"source": "platform", **broken}))


def test_answer_without_a_file_has_an_empty_file_column(sessions, teacher, run_id):
    """Нет файла — пустое значение базы, а не JSON `null`: иначе `file IS NULL` не найдёт."""

    async def scenario():
        await SubmissionRepository(sessions).add_answer(
            teacher.id, text_answer(), run_id=run_id, node_id="show"
        )
        query = select(SubmissionRow.id).where(SubmissionRow.file.is_(None))
        async with sessions() as session:
            return list(await session.scalars(query))

    assert len(asyncio.run(scenario())) == 1
