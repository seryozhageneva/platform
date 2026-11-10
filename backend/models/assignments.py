"""Индивидуальные назначения и блокировка действий над уроком."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.exc import TimeoutError as PoolTimeout

from backend.models.db import Sessions
from backend.models.tables import AssignmentRow, PipelineRow, RunRow


class LessonBusy(Exception):
    """Запрос к этому уроку уже выполняется."""


class LessonLockUnavailable(Exception):
    """Нет свободного соединения для блокировки урока."""


class AssignmentRepository:
    def __init__(self, sessions: Sessions, *, lock_sessions: Sessions | None = None) -> None:
        self._sessions = sessions
        self._lock_sessions = lock_sessions or sessions

    async def create(
        self, teacher_id: UUID, student_id: UUID, pipeline_id: UUID, params: dict[str, Any]
    ) -> AssignmentRow:
        row = AssignmentRow(
            teacher_id=teacher_id, student_id=student_id, pipeline_id=pipeline_id, params=params
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def list_for(self, student_id: UUID) -> list[tuple[UUID, str]]:
        query = (
            select(AssignmentRow.id, PipelineRow.name)
            .join(PipelineRow)
            .where(AssignmentRow.student_id == student_id)
            .order_by(AssignmentRow.created_at, AssignmentRow.id)
        )
        async with self._sessions() as session:
            return [(row.id, row.name) for row in await session.execute(query)]

    async def get_for(self, assignment_id: UUID, student_id: UUID) -> AssignmentRow | None:
        query = select(AssignmentRow).where(
            AssignmentRow.id == assignment_id, AssignmentRow.student_id == student_id
        )
        async with self._sessions() as session:
            return await session.scalar(query)

    async def run_for(self, assignment_id: UUID, student_id: UUID) -> tuple[UUID, str] | None:
        # xmin — номер транзакции, создавшей текущую версию строки PostgreSQL.
        query = select(RunRow.id, literal_column("runs.xmin::text").label("revision")).where(
            RunRow.assignment_id == assignment_id, RunRow.student_id == student_id
        )
        async with self._sessions() as session:
            row = (await session.execute(query)).one_or_none()
            return (row.id, row.revision) if row else None

    async def is_assigned(self, run_id: UUID) -> bool:
        async with self._sessions() as session:
            assignment = await session.scalar(
                select(RunRow.assignment_id).where(RunRow.id == run_id)
            )
        return assignment is not None

    @asynccontextmanager
    async def lock(self, assignment_id: UUID) -> AsyncIterator[None]:
        # Отдельная транзакция держит блокировку до конца запроса, пока движок сохраняет шаги.
        key = int.from_bytes(assignment_id.bytes[:8], "big", signed=True)
        async with self._lock_sessions.begin() as session:
            try:
                acquired = await session.scalar(select(func.pg_try_advisory_xact_lock(key)))
            except PoolTimeout:
                raise LessonLockUnavailable from None
            if not acquired:
                raise LessonBusy
            yield
