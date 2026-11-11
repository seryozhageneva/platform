"""Репозиторий результатов кабинета (ADR 0026, ADR 0027): списки для преподавателя и ученика.

Записывают результаты блоки-получатели через хранилище платформы (`platform_store.py`), здесь
только чтение. Преподаватель видит свои результаты, в том числе адресованные его ученикам;
ученик — только адресованные ему.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import aliased

from backend.models.db import Sessions
from backend.models.tables import CabinetResultRow, UserRow

# Сколько последних результатов показывать: кабинет — не архив.
LIMIT = 100


@dataclass(frozen=True)
class CabinetResult:
    id: uuid.UUID
    run_id: uuid.UUID
    title: str
    content: JsonValue
    student_id: uuid.UUID | None
    student_name: str | None
    created_at: datetime


class CabinetResultRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def list_for_teacher(self, owner_id: uuid.UUID) -> list[CabinetResult]:
        student = aliased(UserRow)
        query = (
            select(CabinetResultRow, student.name)
            .outerjoin(student, student.id == CabinetResultRow.student_id)
            .where(CabinetResultRow.owner_id == owner_id)
            .order_by(CabinetResultRow.created_at.desc(), CabinetResultRow.id)
            .limit(LIMIT)
        )
        async with self._sessions() as session:
            rows = (await session.execute(query)).all()
        return [_result(row, name) for row, name in rows]

    async def list_for_student(self, student_id: uuid.UUID) -> list[CabinetResult]:
        query = (
            select(CabinetResultRow)
            .where(CabinetResultRow.student_id == student_id)
            .order_by(CabinetResultRow.created_at.desc(), CabinetResultRow.id)
            .limit(LIMIT)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(query)).all()
        return [_result(row, None) for row in rows]


def _result(row: CabinetResultRow, student_name: str | None) -> CabinetResult:
    return CabinetResult(
        id=row.id,
        run_id=row.run_id,
        title=row.title,
        content=row.content,
        student_id=row.student_id,
        student_name=student_name,
        created_at=row.created_at,
    )
