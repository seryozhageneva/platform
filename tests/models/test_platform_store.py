"""Хранилище платформы на базе: только свои и только подтверждённые задачи (ADR 0014, 0015),
только свои файлы (ADR 0023)."""

import asyncio
import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from test_task_repo import make

from backend.core.contracts.interfaces import PlatformStore
from backend.core.contracts.ports import FileKind
from backend.models.files import FileRepository
from backend.models.platform_store import PgPlatformStore
from backend.models.tables import FileRow, TaskStatus
from backend.models.tasks import TaskRepository
from backend.models.users import UserRepository

PDF = b"%PDF-1.7\n\x00\xff fake lecture"


def store_of(sessions, owner_id) -> PgPlatformStore:
    return PgPlatformStore(TaskRepository(sessions), FileRepository(sessions), owner_id)


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
        store = PgPlatformStore(tasks, FileRepository(sessions), teacher.id)

        found = await store.find_tasks(topic="logarithms", difficulty=2, subject="math")

        assert [task.id for task in found] == [str(mine.id)]
        assert found[0].topic == "logarithms"
        assert len(await store.find_tasks()) == 3

    asyncio.run(scenario())


def test_get_task_gives_own_approved_task(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        row = await make(tasks, teacher.id)

        task = await PgPlatformStore(tasks, FileRepository(sessions), teacher.id).get_task(
            str(row.id)
        )

        assert task is not None
        assert (task.id, task.answer) == (str(row.id), "3")

    asyncio.run(scenario())


def test_get_task_does_not_give_a_draft(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        draft = await make(tasks, teacher.id, status=TaskStatus.DRAFT)

        assert (
            await PgPlatformStore(tasks, FileRepository(sessions), teacher.id).get_task(
                str(draft.id)
            )
            is None
        )

    asyncio.run(scenario())


def test_get_task_does_not_give_another_teachers_task(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        theirs = await make(tasks, other_teacher.id)

        assert (
            await PgPlatformStore(tasks, FileRepository(sessions), teacher.id).get_task(
                str(theirs.id)
            )
            is None
        )

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
