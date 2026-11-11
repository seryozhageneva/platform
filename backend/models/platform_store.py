"""Хранилище платформы на базе: интерфейс `PlatformStore` (ADR 0014, 0023, 0026).

Хранилище создаётся для одного преподавателя — того, чей запуск идёт. Блок, который его
получил, не называет преподавателя и чужих задач и файлов не видит. Отдаются только
подтверждённые задачи: черновик в урок не попадает.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.contracts.ports import FileKind, FileRef, Task
from backend.models import files as file_rows
from backend.models.db import Sessions
from backend.models.files import FileRepository
from backend.models.tables import CabinetResultRow, FileRow, Role, TaskRow, TaskStatus, UserRow
from backend.models.tasks import TaskRepository, as_contract

_RESULT_NAMESPACE = uuid.UUID("f6e6dfb8-955f-4b4d-a864-a86b7e926d42")


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
