"""Хранилище платформы на базе: только свои и только подтверждённые задачи (ADR 0014, 0015)."""

import asyncio
import uuid

from test_task_repo import make

from backend.core.contracts.interfaces import PlatformStore
from backend.models.platform_store import PgPlatformStore
from backend.models.tables import TaskStatus
from backend.models.tasks import TaskRepository


def test_store_has_the_contract_interface(sessions, teacher):
    assert isinstance(PgPlatformStore(TaskRepository(sessions), teacher.id), PlatformStore)


def test_find_tasks_gives_only_own_approved_tasks(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        mine = await make(tasks, teacher.id, difficulty=2)
        await make(tasks, teacher.id, difficulty=1)
        await make(tasks, teacher.id, difficulty=2, topic="derivatives")
        await make(tasks, teacher.id, difficulty=2, status=TaskStatus.DRAFT)
        await make(tasks, other_teacher.id, difficulty=2)
        store = PgPlatformStore(tasks, teacher.id)

        found = await store.find_tasks(topic="logarithms", difficulty=2, subject="math")

        assert [task.id for task in found] == [str(mine.id)]
        assert found[0].topic == "logarithms"
        assert len(await store.find_tasks()) == 3

    asyncio.run(scenario())


def test_get_task_gives_own_approved_task(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        row = await make(tasks, teacher.id)

        task = await PgPlatformStore(tasks, teacher.id).get_task(str(row.id))

        assert task is not None
        assert (task.id, task.answer) == (str(row.id), "3")

    asyncio.run(scenario())


def test_get_task_does_not_give_a_draft(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        draft = await make(tasks, teacher.id, status=TaskStatus.DRAFT)

        assert await PgPlatformStore(tasks, teacher.id).get_task(str(draft.id)) is None

    asyncio.run(scenario())


def test_get_task_does_not_give_another_teachers_task(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        theirs = await make(tasks, other_teacher.id)

        assert await PgPlatformStore(tasks, teacher.id).get_task(str(theirs.id)) is None

    asyncio.run(scenario())


def test_get_task_with_a_strange_number_is_none(sessions, teacher):
    async def scenario():
        store = PgPlatformStore(TaskRepository(sessions), teacher.id)

        assert await store.get_task("не-номер") is None
        assert await store.get_task(str(uuid.uuid4())) is None

    asyncio.run(scenario())
