"""Хранилище платформы на базе: интерфейс `PlatformStore` (ADR 0014, 0023, 0026, 0031).

Хранилище создаётся для одного преподавателя — того, чей запуск идёт. Блок, который его
получил, не называет преподавателя и чужих задач, файлов и учеников не видит. Отдаются
только подтверждённые задачи: черновик в урок не попадает.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from pydantic import JsonValue
from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.contracts.interfaces import StudentResults, WorkResult
from backend.core.contracts.ports import FileKind, FileRef, Task
from backend.models import files as file_rows
from backend.models.db import Sessions
from backend.models.files import FileRepository
from backend.models.tables import (
    CabinetResultRow,
    EventRow,
    FileRow,
    Role,
    RunRow,
    SubmissionRow,
    TaskRow,
    TaskStatus,
    UserRow,
)
from backend.models.tasks import TaskRepository, as_contract

_RESULT_NAMESPACE = uuid.UUID("f6e6dfb8-955f-4b4d-a864-a86b7e926d42")
# Событие ИИ-тьютора: подсказка проверена контролёром; ученик её получил, если она одобрена.
_HINT_EVENT = "hint_checked"


def _key(value: str) -> uuid.UUID | None:
    """Номер, который не похож на номер в базе, — это «нет такого», а не ошибка."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class PgPlatformStore:
    def __init__(
        self, sessions: Sessions, owner_id: uuid.UUID, *, run_id: uuid.UUID, node_id: str
    ) -> None:
        self._sessions = sessions
        self._tasks = TaskRepository(sessions)
        self._files = FileRepository(sessions)
        self._owner_id = owner_id
        self._run_id = run_id
        self._node_id = node_id

    async def find_tasks(
        self,
        *,
        topic: str | None = None,
        difficulty: int | None = None,
        subject: str | None = None,
    ) -> list[Task]:
        rows = await self._tasks.find(
            self._owner_id, subject=subject, topic=topic, difficulty=difficulty
        )
        return [as_contract(row) for row in rows]

    async def get_task(self, task_id: str) -> Task | None:
        key = _key(task_id)
        if key is None:
            return None
        row = await self._tasks.get(self._owner_id, key)
        if row is None or row.status != TaskStatus.APPROVED:
            return None
        return as_contract(row)

    async def get_file(self, file_id: str) -> FileRef | None:
        key = _key(file_id)
        if key is None:
            return None
        row = await self._files.get(self._owner_id, key)
        return None if row is None else file_rows.as_contract(row)

    async def read_file(self, file_id: str) -> bytes | None:
        key = _key(file_id)
        if key is None:
            return None
        return await self._files.read(self._owner_id, key)

    async def find_results(self, *, since: datetime) -> list[StudentResults]:
        if since.tzinfo is None:
            raise ValueError("время `since` нужно с часовым поясом")
        students = (
            select(UserRow.id, UserRow.name)
            .where(UserRow.owner_id == self._owner_id, UserRow.role == Role.STUDENT)
            .order_by(UserRow.name, UserRow.id)
        )
        works = (
            select(SubmissionRow, TaskRow.topic)
            .outerjoin(
                TaskRow,
                (cast(TaskRow.id, String) == SubmissionRow.task_id)
                & (TaskRow.owner_id == self._owner_id),
            )
            .where(
                SubmissionRow.owner_id == self._owner_id,
                SubmissionRow.student_id.is_not(None),
                SubmissionRow.created_at >= since,
            )
            .order_by(SubmissionRow.created_at, SubmissionRow.id)
        )
        hints = (
            select(RunRow.student_id, func.count(EventRow.id))
            .join(RunRow, RunRow.id == EventRow.run_id)
            .where(
                RunRow.teacher_id == self._owner_id,
                RunRow.student_id.is_not(None),
                EventRow.type == _HINT_EVENT,
                EventRow.data["approved"].as_boolean().is_(True),
                EventRow.created_at >= since,
            )
            .group_by(RunRow.student_id)
        )
        async with self._sessions() as session:
            people = (await session.execute(students)).all()
            done = (await session.execute(works)).all()
            given: dict[uuid.UUID, int] = dict((await session.execute(hints)).all())
        by_student: dict[uuid.UUID, list[WorkResult]] = defaultdict(list)
        for row, topic in done:
            by_student[row.student_id].append(_work(row, topic))
        return [
            StudentResults(
                student_id=str(student_id),
                name=name,
                works=by_student.get(student_id, []),
                hints=given.get(student_id, 0),
            )
            for student_id, name in people
        ]

    async def save_task(self, task: Task, *, key: str) -> Task:
        async with self._write() as session:
            row = await self._insert_once(
                session,
                TaskRow,
                key,
                status=TaskStatus.APPROVED,
                **task.model_dump(exclude={"id"}),
            )
        return as_contract(row)

    async def save_file(
        self, *, key: str, name: str, kind: FileKind, media_type: str, content: bytes
    ) -> FileRef:
        async with self._write() as session:
            row = await self._insert_once(
                session,
                FileRow,
                key,
                name=name,
                kind=kind,
                media_type=media_type,
                size=len(content),
                content=content,
            )
        return file_rows.as_contract(row)

    async def publish_result(
        self, *, key: str, title: str, content: JsonValue, student_id: str | None = None
    ) -> str:
        async with self._write() as session:
            recipient = None
            if student_id is not None:
                recipient = await session.scalar(
                    select(UserRow.id).where(
                        UserRow.id == _key(student_id),
                        UserRow.owner_id == self._owner_id,
                        UserRow.role == Role.STUDENT,
                    )
                )
                if recipient is None:
                    raise ValueError("ученик не найден")
            row = await self._insert_once(
                session,
                CabinetResultRow,
                key,
                run_id=self._run_id,
                node_id=self._node_id,
                title=title,
                content=content,
                student_id=recipient,
            )
        return str(row.id)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions.begin() as session:
                yield session
        except SQLAlchemyError as error:
            # Ошибка базы может содержать текст задачи, результат или байты файла.
            raise RuntimeError(f"не удалось записать результат ({type(error).__name__})") from None

    async def _insert_once[Row: (TaskRow, FileRow, CabinetResultRow)](
        self, session: AsyncSession, table: type[Row], key: str, **values: Any
    ) -> Row:
        scope = (str(self._owner_id), str(self._run_id), self._node_id, table.__tablename__, key)
        record_id = uuid.uuid5(_RESULT_NAMESPACE, json.dumps(scope))
        await session.execute(
            insert(table)
            .values(id=record_id, owner_id=self._owner_id, **values)
            .on_conflict_do_nothing(index_elements=[table.id])
        )
        return (
            await session.scalars(
                select(table).where(table.id == record_id, table.owner_id == self._owner_id)
            )
        ).one()


def _work(row: SubmissionRow, topic: str | None) -> WorkResult:
    """Итог работы для блока: без текста ответа, файла и комментария (ADR 0031)."""
    return WorkResult(
        task_id=row.task_id,
        topic=topic,
        source=row.source,
        submitted_at=row.created_at,
        status=row.verdict_status or "unchecked",
        correct=row.correct,
        score=row.score,
        max_score=row.max_score,
    )
