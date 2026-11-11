"""Подключения преподавателя к внешним системам (ADR 0028): адрес и зашифрованный токен.

Токен шифруется ключом `PLATFORM_SECRET_KEY` из `.env` (Fernet из библиотеки cryptography:
шифрование и проверка целостности вместе). В базе лежит только шифр. Расшифрованный токен
отдаёт только `credentials()` — его вызывает слой сборки в момент вызова MCP-сервера.
Наружу через API токен не выходит никогда.
"""

import uuid
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from backend.models.db import ROOT, Sessions
from backend.models.tables import ConnectionKind, ConnectionRow


class _SecretSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    platform_secret_key: SecretStr = SecretStr("")


class SecretBox:
    """Шифрует и расшифровывает токены подключений одним ключом платформы."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            # `from None`: в исходной ошибке может оказаться сам ключ.
            raise RuntimeError(
                "PLATFORM_SECRET_KEY в файле .env записан с ошибкой: нужен ключ Fernet. "
                "Как его создать — в .env.example."
            ) from None

    @classmethod
    def from_env(cls) -> "SecretBox":
        key = _SecretSettings().platform_secret_key.get_secret_value()
        if not key:
            raise RuntimeError(
                "Не задан PLATFORM_SECRET_KEY в файле .env: без него подключения не сохранить "
                "и не прочитать. Как его создать — в .env.example."
            )
        return cls(key)

    def seal(self, secret: str) -> bytes:
        return self._fernet.encrypt(secret.encode("utf-8"))

    def open(self, sealed: bytes) -> str:
        try:
            return self._fernet.decrypt(sealed).decode("utf-8")
        except InvalidToken:
            raise RuntimeError(
                "токен подключения не расшифровывается: ключ PLATFORM_SECRET_KEY сменился. "
                "Создай подключение заново"
            ) from None


@dataclass(frozen=True)
class Credentials:
    url: str
    token: str

    def __repr__(self) -> str:
        return f"Credentials(url={self.url!r}, token=***)"


class ConnectionRepository:
    def __init__(self, sessions: Sessions, box: SecretBox) -> None:
        self._sessions = sessions
        self._box = box

    async def save(
        self, owner_id: uuid.UUID, kind: ConnectionKind, *, url: str, token: str
    ) -> ConnectionRow:
        """Создаёт подключение или заменяет прежнее того же вида."""
        sealed = self._box.seal(token)
        statement = (
            insert(ConnectionRow)
            .values(id=uuid.uuid4(), owner_id=owner_id, kind=kind, url=url, token_encrypted=sealed)
            .on_conflict_do_update(
                index_elements=[ConnectionRow.owner_id, ConnectionRow.kind],
                set_={"url": url, "token_encrypted": sealed, "updated_at": func.now()},
            )
            .returning(ConnectionRow)
        )
        async with self._sessions.begin() as session:
            return (await session.scalars(statement)).one()

    async def list(self, owner_id: uuid.UUID) -> list[ConnectionRow]:
        query = (
            select(ConnectionRow)
            .where(ConnectionRow.owner_id == owner_id)
            .order_by(ConnectionRow.kind)
        )
        async with self._sessions() as session:
            return list(await session.scalars(query))

    async def delete(self, owner_id: uuid.UUID, kind: ConnectionKind) -> bool:
        statement = delete(ConnectionRow).where(
            ConnectionRow.owner_id == owner_id, ConnectionRow.kind == kind
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).rowcount > 0

    async def credentials(self, owner_id: uuid.UUID, kind: ConnectionKind) -> Credentials | None:
        """Адрес и расшифрованный токен своего подключения; `None` — подключения нет."""
        query = select(ConnectionRow).where(
            ConnectionRow.owner_id == owner_id, ConnectionRow.kind == kind
        )
        async with self._sessions() as session:
            row = await session.scalar(query)
        if row is None:
            return None
        return Credentials(url=row.url, token=self._box.open(row.token_encrypted))
