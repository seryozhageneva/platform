"""Репозиторий банка задач: поиск по предмету, теме и сложности в пределах владельца."""

import asyncio
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from backend.core.contracts.ports import CheckMethod, DataType, PortType, value_problems
from backend.models.tables import TaskStatus
from backend.models.tasks import TaskRepository, as_contract


def make(tasks: TaskRepository, owner_id: uuid.UUID, **fields):
    """Выдуманная подтверждённая задача; отличия задаются в `fields`."""
    defaults = {
        "subject": "math",
        "topic": "logarithms",
        "difficulty": 1,
        "statement": "Вычислите $\\log_2 8$.",
        "check_method": CheckMethod.SHORT_ANSWER,
        "answer": "3",
        "status": TaskStatus.APPROVED,
    }
    return tasks.create(owner_id, **{**defaults, **fields})


def test_tasks_are_found_by_subject_topic_and_difficulty(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        easy = await make(tasks, teacher.id)
        hard = await make(tasks, teacher.id, difficulty=2)
        other_topic = await make(tasks, teacher.id, topic="derivatives")
        other_subject = await make(tasks, teacher.id, subject="informatics", topic="loops")

        async def ids(**conditions):
            return {row.id for row in await tasks.find(teacher.id, **conditions)}

        assert await ids(subject="math", topic="logarithms", difficulty=1) == {easy.id}
        assert await ids(subject="math", topic="logarithms") == {easy.id, hard.id}
        assert await ids(subject="math") == {easy.id, hard.id, other_topic.id}
        assert await ids() == {easy.id, hard.id, other_topic.id, other_subject.id}
        assert await ids(topic="integrals") == set()

    asyncio.run(scenario())


def test_drafts_are_not_given_out_by_default(sessions, teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        approved = await make(tasks, teacher.id)
        draft = await make(tasks, teacher.id, status=TaskStatus.DRAFT)

        assert [row.id for row in await tasks.find(teacher.id)] == [approved.id]
        assert [row.id for row in await tasks.find(teacher.id, status=TaskStatus.DRAFT)] == [
            draft.id
        ]
        assert len(await tasks.find(teacher.id, status=None)) == 2

    asyncio.run(scenario())


def test_new_task_is_a_draft(sessions, teacher):
    async def scenario():
        row = await TaskRepository(sessions).create(
            teacher.id,
            subject="math",
            topic="logarithms",
            difficulty=1,
            statement="Вычислите $\\log_3 9$.",
            check_method=CheckMethod.SHORT_ANSWER,
        )
        assert row.status == TaskStatus.DRAFT

    asyncio.run(scenario())


@pytest.mark.parametrize("method", list(CheckMethod))
def test_stored_task_is_a_valid_contract_task(sessions, teacher, method):
    """Каждый способ проверки из контракта хранится в базе и возвращается как `Task`."""

    async def scenario():
        tasks = TaskRepository(sessions)
        created = await make(
            tasks,
            teacher.id,
            check_method=method,
            solution="$2^3 = 8$",
            tests="assert solve() == 3",
            rubric="Верный метод — 2 балла",
        )
        task = as_contract(await tasks.get(teacher.id, created.id))

        assert value_problems(DataType(type=PortType.TASK), task.model_dump(mode="json")) == []
        assert (task.id, task.check_method) == (str(created.id), method)
        assert (task.answer, task.solution) == ("3", "$2^3 = 8$")
        assert (task.tests, task.rubric) == ("assert solve() == 3", "Верный метод — 2 балла")

    asyncio.run(scenario())


def test_teacher_does_not_see_tasks_of_another_teacher(sessions, teacher, other_teacher):
    async def scenario():
        tasks = TaskRepository(sessions)
        own = await make(tasks, teacher.id)
        foreign = await make(tasks, other_teacher.id)

        assert [row.id for row in await tasks.find(teacher.id)] == [own.id]
        assert await tasks.get(teacher.id, foreign.id) is None
        assert (await tasks.get(other_teacher.id, foreign.id)).id == foreign.id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "broken",
    [{"difficulty": 0}, {"check_method": "by_eye"}, {"status": "published"}],
    ids=["difficulty", "check_method", "status"],
)
def test_database_rejects_impossible_values(sessions, teacher, broken):
    async def scenario():
        with pytest.raises(IntegrityError):
            await make(TaskRepository(sessions), teacher.id, **broken)

    asyncio.run(scenario())
