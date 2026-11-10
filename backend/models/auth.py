"""Хранилище учётных сеансов и личных ссылок."""

import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import delete, select, update

from backend.models.db import Sessions
from backend.models.tables import LoginSessionRow, Role, UserRow

SESSION_TTL = timedelta(hours=8)
LINK_TTL = timedelta(days=30)


def _digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


class AuthRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def start_teacher(self, user_id: uuid.UUID) -> tuple[str, datetime]:
        async with self._sessions.begin() as db:
            token, expiry = token_urlsafe(32), datetime.now(UTC) + SESSION_TTL
            db.add(LoginSessionRow(token_hash=_digest(token), user_id=user_id, expires_at=expiry))
        return token, expiry

    async def start_student(self, link: str) -> tuple[UserRow, str, datetime] | None:
        async with self._sessions.begin() as db:
            # Та же блокировка строки ученика, что при отзыве или замене ссылки.
            student = await db.scalar(
                select(UserRow)
                .where(UserRow.role == Role.STUDENT, UserRow.link_token_hash == _digest(link))
                .with_for_update()
            )
            now = datetime.now(UTC)
            if student is None or student.link_expires_at is None or student.link_expires_at <= now:
                return None
            token = token_urlsafe(32)
            expiry = min(now + SESSION_TTL, student.link_expires_at)
            db.add(
                LoginSessionRow(token_hash=_digest(token), user_id=student.id, expires_at=expiry)
            )
            return student, token, expiry

    async def current(self, token: str) -> UserRow | None:
        async with self._sessions() as db:
            return await db.scalar(
                select(UserRow)
                .join(LoginSessionRow, UserRow.id == LoginSessionRow.user_id)
                .where(
                    LoginSessionRow.token_hash == _digest(token),
                    LoginSessionRow.expires_at > datetime.now(UTC),
                )
            )

    async def end(self, token: str) -> None:
        async with self._sessions.begin() as db:
            await db.execute(
                delete(LoginSessionRow).where(LoginSessionRow.token_hash == _digest(token))
            )

    async def change_link(
        self, owner_id: uuid.UUID, student_id: uuid.UUID, *, issue: bool
    ) -> UserRow | tuple[str, datetime] | None:
        async with self._sessions.begin() as db:
            student = await db.scalar(
                select(UserRow)
                .where(
                    UserRow.id == student_id,
                    UserRow.owner_id == owner_id,
                    UserRow.role == Role.STUDENT,
                )
                .with_for_update()
            )
            if student is None:
                return None
            await db.execute(delete(LoginSessionRow).where(LoginSessionRow.user_id == student.id))
            if issue:
                link, expiry = token_urlsafe(32), datetime.now(UTC) + LINK_TTL
                student.link_token_hash, student.link_expires_at = _digest(link), expiry
                return link, expiry
            student.link_token_hash = student.link_expires_at = None
            return student

    async def set_initial_password(self, user_id: uuid.UUID, password_hash: str) -> bool:
        async with self._sessions.begin() as db:
            result = await db.execute(
                update(UserRow)
                .where(
                    UserRow.id == user_id,
                    UserRow.role == Role.TEACHER,
                    UserRow.password_hash.is_(None),
                )
                .values(password_hash=password_hash)
                .returning(UserRow.id)
            )
            return result.scalar_one_or_none() is not None
