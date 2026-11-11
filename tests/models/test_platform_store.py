"""Хранилище платформы на базе: только свои и только подтверждённые задачи (ADR 0014, 0015),
только свои файлы (ADR 0023), запись результатов без повторов (ADR 0026)."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from test_task_repo import make

from backend.core.contracts.interfaces import PlatformStore
from backend.core.contracts.pipeline import load_pipeline
from backend.core.contracts.ports import CheckMethod, FileKind, Task
from backend.core.contracts.state import RunStatus
from backend.models.files import FileRepository
from backend.models.pipelines import PipelineRepository
from backend.models.platform_store import PgPlatformStore
from backend.models.tables import CabinetResultRow, FileRow, RunRow, TaskRow, TaskStatus
from backend.models.tasks import TaskRepository
from backend.models.users import UserRepository

PDF = b"%PDF-1.7\n\x00\xff fake lecture"
SCENARIO_1 = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "pipelines"
    / "scenario-1-training.json"
)


def store_of(sessions, owner_id, run_id=None, node_id="save") -> PgPlatformStore:
    # Для чтения запуск не нужен: номер запуска важен только для записи.
    return PgPlatformStore(sessions, owner_id, run_id=run_id or uuid.uuid4(), node_id=node_id)


async def upload(sessions, owner_id, **fields):
    defaults = dict(
        name="лекция.pdf", kind=FileKind.DOCUMENT, media_type="application/pdf", content=PDF
    )
    return await FileRepository(sessions).create(owner_id, **(defaults | fields))


def test_store_has_the_contract_interface(sessions, teacher):
    assert isinstance(store_of(sessions, teacher.id), PlatformStore)


def test_find_tasks_gives_only_own_approved_tasks(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        mine = await make(tasks, teacher.id, difficulty=2)
        await make(tasks, teacher.id, difficulty=1)
        await make(tasks, teacher.id, difficulty=2, topic="derivatives")
        await make(tasks, teacher.id, difficulty=2, status=TaskStatus.DRAFT)
        await make(tasks, other_teacher.id, difficulty=2)
        store = store_of(sessions, teacher.id)

        found = await store.find_tasks(topic="logarithms", difficulty=2, subject="math")

        assert [task.id for task in found] == [str(mine.id)]
        assert found[0].topic == "logarithms"
        assert len(await store.find_tasks()) == 3

    asyncio.run(scenario())


def test_get_task_gives_own_approved_task(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        row = await make(tasks, teacher.id)

        task = await store_of(sessions, teacher.id).get_task(str(row.id))

        assert task is not None
        assert (task.id, task.answer) == (str(row.id), "3")

    asyncio.run(scenario())


def test_get_task_does_not_give_a_draft(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        draft = await make(tasks, teacher.id, status=TaskStatus.DRAFT)

        assert await store_of(sessions, teacher.id).get_task(str(draft.id)) is None

    asyncio.run(scenario())


def test_get_task_does_not_give_another_teachers_task(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        theirs = await make(tasks, other_teacher.id)

        assert await store_of(sessions, teacher.id).get_task(str(theirs.id)) is None

    asyncio.run(scenario())


def test_get_task_with_a_strange_number_is_none(sessions, teacher):
    async def scenario():
        store = store_of(sessions, teacher.id)

        assert await store.get_task("не-номер") is None
        assert await store.get_task(str(uuid.uuid4())) is None

    asyncio.run(scenario())


def test_get_and_read_own_file(sessions, teacher):
    async def scenario():
        student = await UserRepository(sessions).create_student(teacher.id, name="Ученик 1")
        row = await upload(sessions, teacher.id, student_id=student.id)
        store = store_of(sessions, teacher.id)

        ref = await store.get_file(str(row.id))

        assert ref is not None
        assert (ref.id, ref.name, ref.kind, ref.media_type) == (
            str(row.id),
            "лекция.pdf",
            FileKind.DOCUMENT,
            "application/pdf",
        )
        assert (ref.size, ref.student_id) == (len(PDF), str(student.id))
        # Байты возвращаются ровно такими, какими были загружены.
        assert await store.read_file(str(row.id)) == PDF

    asyncio.run(scenario())


def test_file_description_does_not_load_content(sessions, teacher):
    async def scenario():
        row = await upload(sessions, teacher.id)
        found = await FileRepository(sessions).get(teacher.id, row.id)
        assert found is not None
        assert "content" in inspect(found).unloaded

    asyncio.run(scenario())


def test_another_teachers_file_is_not_visible(sessions, teacher, other_teacher):
    async def scenario():
        theirs = await upload(sessions, other_teacher.id)
        store = store_of(sessions, teacher.id)

        assert await store.get_file(str(theirs.id)) is None
        assert await store.read_file(str(theirs.id)) is None

    asyncio.run(scenario())


def test_file_with_a_strange_number_is_none(sessions, teacher):
    async def scenario():
        store = store_of(sessions, teacher.id)

        assert await store.get_file("не-номер") is None
        assert await store.read_file("не-номер") is None
        assert await store.get_file(str(uuid.uuid4())) is None
        assert await store.read_file(str(uuid.uuid4())) is None

    asyncio.run(scenario())


def test_each_file_kind_is_accepted(sessions, teacher):
    async def scenario():
        for kind in FileKind:
            row = await upload(sessions, teacher.id, kind=kind, name=f"{kind}.bin")
            ref = await store_of(sessions, teacher.id).get_file(str(row.id))
            assert ref is not None and ref.kind is kind

    asyncio.run(scenario())


def test_database_rejects_size_that_differs_from_content(sessions, teacher):
    async def scenario():
        row = FileRow(
            owner_id=teacher.id,
            name="x.pdf",
            kind=FileKind.DOCUMENT,
            media_type="application/pdf",
            size=999,
            content=PDF,
        )
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(row)

    asyncio.run(scenario())


# --- Запись (ADR 0026) ---


def new_task(**fields) -> Task:
    defaults = dict(
        id="из-пайплайна",
        subject="math",
        topic="logarithms",
        difficulty=2,
        statement="Вычислите log2(8).",
        check_method=CheckMethod.SHORT_ANSWER,
        answer="3",
    )
    return Task(**(defaults | fields))


async def start_run(sessions, teacher_id) -> uuid.UUID:
    pipeline = await PipelineRepository(sessions).create(teacher_id, load_pipeline(SCENARIO_1))
    row = RunRow(pipeline_id=pipeline.id, pipeline_version=1, status=RunStatus.RUNNING, state={})
    async with sessions.begin() as session:
        session.add(row)
    return row.id


async def count(sessions, table) -> int:
    async with sessions() as session:
        return await session.scalar(select(func.count()).select_from(table))


def test_saved_task_is_approved_and_found_by_the_store(sessions, teacher):
    async def scenario():
        store = store_of(sessions, teacher.id, await start_run(sessions, teacher.id))

        saved = await store.save_task(new_task(), key="task-1")

        # Номер выдаёт банк, а не пайплайн.
        assert saved.id != "из-пайплайна"
        assert await store.get_task(saved.id) == saved
        assert [task.id for task in await store.find_tasks(topic="logarithms")] == [saved.id]
        async with sessions() as session:
            row = await session.get(TaskRow, uuid.UUID(saved.id))
        assert row is not None and (row.owner_id, row.status) == (teacher.id, TaskStatus.APPROVED)

    asyncio.run(scenario())


def test_repeat_with_the_same_key_returns_the_first_record(sessions, teacher):
    """Повтор блока после сбоя не создаёт вторую задачу, файл или результат."""

    async def scenario():
        store = store_of(sessions, teacher.id, await start_run(sessions, teacher.id))

        first_task = await store.save_task(new_task(), key="k")
        again_task = await store.save_task(new_task(statement="Другое условие"), key="k")
        first_file = await store.save_file(
            key="k",
            name="a.pdf",
            kind=FileKind.DOCUMENT,
            media_type="application/pdf",
            content=PDF,
        )
        again_file = await store.save_file(
            key="k",
            name="b.pdf",
            kind=FileKind.DOCUMENT,
            media_type="application/pdf",
            content=b"other",
        )
        first_result = await store.publish_result(key="k", title="Итог", content={"a": 1})
        again_result = await store.publish_result(key="k", title="Итог", content={"a": 2})

        assert again_task == first_task
        assert again_file == first_file
        assert again_result == first_result
        assert (await count(sessions, TaskRow), await count(sessions, FileRow)) == (1, 1)
        assert await count(sessions, CabinetResultRow) == 1

    asyncio.run(scenario())


def test_same_key_in_another_node_or_run_is_a_new_record(sessions, teacher):
    async def scenario():
        run_a = await start_run(sessions, teacher.id)
        run_b = await start_run(sessions, teacher.id)

        ids = {
            await store_of(sessions, teacher.id, run_a, "save").publish_result(
                key="k", title="Итог", content=1
            ),
            await store_of(sessions, teacher.id, run_a, "other").publish_result(
                key="k", title="Итог", content=1
            ),
            await store_of(sessions, teacher.id, run_b, "save").publish_result(
                key="k", title="Итог", content=1
            ),
        }

        assert len(ids) == 3

    asyncio.run(scenario())


def test_saved_file_is_teachers_and_readable(sessions, teacher):
    async def scenario():
        store = store_of(sessions, teacher.id, await start_run(sessions, teacher.id))

        ref = await store.save_file(
            key="report",
            name="отчёт.pdf",
            kind=FileKind.DOCUMENT,
            media_type="application/pdf",
            content=PDF,
        )

        assert (ref.name, ref.size, ref.student_id) == ("отчёт.pdf", len(PDF), None)
        assert await store.get_file(ref.id) == ref
        assert await store.read_file(ref.id) == PDF

    asyncio.run(scenario())


def test_result_goes_to_the_teacher_or_own_student(sessions, teacher):
    async def scenario():
        run_id = await start_run(sessions, teacher.id)
        student = await UserRepository(sessions).create_student(teacher.id, name="Ученик 1")
        store = store_of(sessions, teacher.id, run_id, "cabinet")

        for_teacher = await store.publish_result(
            key="all", title="Итоги группы", content={"solved": [3, 5]}
        )
        for_student = await store.publish_result(
            key="one", title="Ваш итог", content=["верно"], student_id=str(student.id)
        )

        async with sessions() as session:
            rows = {
                str(row.id): row for row in (await session.scalars(select(CabinetResultRow))).all()
            }
        teacher_row, student_row = rows[for_teacher], rows[for_student]
        assert (teacher_row.owner_id, teacher_row.run_id, teacher_row.node_id) == (
            teacher.id,
            run_id,
            "cabinet",
        )
        assert (teacher_row.student_id, teacher_row.content) == (None, {"solved": [3, 5]})
        assert (student_row.student_id, student_row.content) == (student.id, ["верно"])

    asyncio.run(scenario())


@pytest.mark.parametrize("whose", ["other_teacher", "strange", "teacher_himself"])
def test_result_for_a_foreign_or_unknown_student_is_refused(
    sessions, teacher, other_teacher, whose
):
    async def scenario():
        run_id = await start_run(sessions, teacher.id)
        theirs = await UserRepository(sessions).create_student(other_teacher.id, name="Чужой")
        student_id = {
            "other_teacher": str(theirs.id),
            "strange": "не-номер",
            # Преподаватель — не ученик, даже свой собственный.
            "teacher_himself": str(teacher.id),
        }[whose]

        with pytest.raises(ValueError, match="ученик не найден"):
            await store_of(sessions, teacher.id, run_id).publish_result(
                key="k", title="Итог", content=1, student_id=student_id
            )
        assert await count(sessions, CabinetResultRow) == 0

    asyncio.run(scenario())


def test_database_error_does_not_leak_the_content(sessions, teacher):
    """Без запуска в базе запись не проходит, а текст ошибки не повторяет данные."""

    async def scenario():
        store = store_of(sessions, teacher.id, uuid.uuid4())

        with pytest.raises(RuntimeError) as error:
            await store.publish_result(key="k", title="Секретный итог", content="ответы")

        assert "Секретный" not in str(error.value) and "ответы" not in str(error.value)
        assert error.value.__cause__ is None

    asyncio.run(scenario())


def test_content_that_is_not_json_is_a_clear_error(sessions, teacher):
    async def scenario():
        store = store_of(sessions, teacher.id, await start_run(sessions, teacher.id))

        with pytest.raises(RuntimeError, match="не удалось записать результат"):
            await store.publish_result(key="k", title="Итог", content={"x": object()})
        assert await count(sessions, CabinetResultRow) == 0

    asyncio.run(scenario())
