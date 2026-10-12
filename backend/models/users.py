"""Репозиторий людей: преподаватели и их ученики.

Один вызов — одна транзакция. Вход по паролю и по личной ссылке появится в задаче 13;
здесь только создание и поиск.
"""

import uuid

from sqlalchemy import select

from backend.models.db import Sessions
from backend.models.tables import Role, UserRow


class UserRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create_teacher(
        self,
        *,
        name: str,
        email: str,
        password_hash: str | None = None,
        role: Role = Role.TEACHER,
    ) -> UserRow:
        """Почта хранится строчными буквами: `A@b.ru` и `a@b.ru` — один человек."""
        row = UserRow(role=role, name=name, email=_normalize(email), password_hash=password_hash)
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def create_student(self, owner_id: uuid.UUID, *, name: str) -> UserRow:
        """`name` — имя или псевдоним; больше об ученике ничего не требуется."""
        row = UserRow(role=Role.STUDENT, name=name, owner_id=owner_id)
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def get(self, user_id: uuid.UUID) -> UserRow | None:
        async with self._sessions() as session:
            return await session.get(UserRow, user_id)

    async def find_by_email(self, email: str) -> UserRow | None:
        async with self._sessions() as session:
            return await session.scalar(select(UserRow).where(UserRow.email == _normalize(email)))

    async def list_students(self, owner_id: uuid.UUID) -> list[UserRow]:
        """Только ученики этого преподавателя."""
        query = (
            select(UserRow)
            .where(UserRow.owner_id == owner_id, UserRow.role == Role.STUDENT)
            .order_by(UserRow.created_at, UserRow.name)
        )
        async with self._sessions() as session:
            return list(await session.scalars(query))


def _normalize(email: str) -> str:
    return email.strip().lower()
