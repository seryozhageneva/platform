"""Репозиторий людей: преподаватели и их ученики.

Один вызов — одна транзакция. Здесь создание, поиск и контакты пользователей.
Вход по паролю и по личной ссылке обслуживает отдельное хранилище сеансов.
"""

import uuid

from sqlalchemy import select, update

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

    async def get_student(self, owner_id: uuid.UUID, student_id: uuid.UUID) -> UserRow | None:
        async with self._sessions() as session:
            return await session.scalar(select(UserRow).where(*_own_student(owner_id, student_id)))

    async def set_notification_contacts(
        self,
        owner_id: uuid.UUID,
        student_id: uuid.UUID,
        *,
        email: str | None,
        telegram_id: int | None,
    ) -> UserRow | None:
        query = (
            update(UserRow)
            .where(*_own_student(owner_id, student_id))
            .values(notification_email=email, telegram_id=telegram_id)
            .returning(UserRow)
        )
        async with self._sessions.begin() as session:
            return await session.scalar(query)

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


def _own_student(owner_id: uuid.UUID, student_id: uuid.UUID):
    return (UserRow.id == student_id, UserRow.owner_id == owner_id, UserRow.role == Role.STUDENT)
