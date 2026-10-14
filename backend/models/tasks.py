"""Репозиторий банка задач: создать задачу и найти задачи по предмету, теме и сложности.

Задача принадлежит преподавателю-автору; поиск всегда идёт в пределах владельца. Банк у
каждого преподавателя свой (ADR 0015). Через API банк читает и пишет преподаватель
(`backend/api/tasks.py`), блоки читают его через хранилище платформы (`platform_store.py`).
"""

import uuid

from sqlalchemy import select

from backend.core.contracts.ports import CheckMethod, Task
from backend.models.db import Sessions
from backend.models.tables import TaskRow, TaskStatus


class TaskRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(
        self,
        owner_id: uuid.UUID,
        *,
        subject: str,
        topic: str,
        difficulty: int,
        statement: str,
        check_method: CheckMethod,
        answer: str | None = None,
        solution: str | None = None,
        tests: str | None = None,
        rubric: str | None = None,
        status: TaskStatus = TaskStatus.DRAFT,
    ) -> TaskRow:
        row = TaskRow(
            owner_id=owner_id,
            subject=subject,
            topic=topic,
            difficulty=difficulty,
            statement=statement,
            check_method=check_method,
            answer=answer,
            solution=solution,
            tests=tests,
            rubric=rubric,
            status=status,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def update(
        self,
        owner_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        subject: str,
        topic: str,
        difficulty: int,
        statement: str,
        check_method: CheckMethod,
        answer: str | None,
        solution: str | None,
        tests: str | None,
        rubric: str | None,
        status: TaskStatus,
    ) -> TaskRow | None:
        """Заменяет все поля своей задачи; `None` — такой задачи среди своих нет."""
        query = select(TaskRow).where(TaskRow.id == task_id, TaskRow.owner_id == owner_id)
        async with self._sessions.begin() as session:
            row = await session.scalar(query)
            if row is None:
                return None
            row.subject = subject
            row.topic = topic
            row.difficulty = difficulty
            row.statement = statement
            row.check_method = check_method
            row.answer = answer
            row.solution = solution
            row.tests = tests
            row.rubric = rubric
            row.status = status
            # Время правки ставит сама база: читаем его, пока сессия открыта.
            await session.flush()
            await session.refresh(row)
        return row

    async def get(self, owner_id: uuid.UUID, task_id: uuid.UUID) -> TaskRow | None:
        query = select(TaskRow).where(TaskRow.id == task_id, TaskRow.owner_id == owner_id)
        async with self._sessions() as session:
            return await session.scalar(query)

    async def find(
        self,
        owner_id: uuid.UUID,
        *,
        subject: str | None = None,
        topic: str | None = None,
        difficulty: int | None = None,
        status: TaskStatus | None = TaskStatus.APPROVED,
    ) -> list[TaskRow]:
        """Задачи преподавателя по условиям; незаданное условие не учитывается.

        По умолчанию выдаются только подтверждённые задачи: черновик в урок не попадает.
        `status=None` — задачи в любом статусе.
        """
        query = select(TaskRow).where(TaskRow.owner_id == owner_id)
        if subject is not None:
            query = query.where(TaskRow.subject == subject)
        if topic is not None:
            query = query.where(TaskRow.topic == topic)
        if difficulty is not None:
            query = query.where(TaskRow.difficulty == difficulty)
        if status is not None:
            query = query.where(TaskRow.status == status)
        async with self._sessions() as session:
            return list(await session.scalars(query.order_by(TaskRow.created_at, TaskRow.id)))


def as_contract(row: TaskRow) -> Task:
    """Запись банка в виде типа `Task` из контракта — так задача идёт по пайплайну."""
    return Task(
        id=str(row.id),
        subject=row.subject,
        topic=row.topic,
        difficulty=row.difficulty,
        statement=row.statement,
        check_method=CheckMethod(row.check_method),
        answer=row.answer,
        solution=row.solution,
        tests=row.tests,
        rubric=row.rubric,
    )
