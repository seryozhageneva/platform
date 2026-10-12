"""Подключение к базе данных.

Адрес базы берётся из переменной `DATABASE_URL` (файл `.env`). На своём компьютере её можно
не заполнять: адрес собирается из `POSTGRES_PASSWORD` — того же пароля, с которым
`docker compose` создаёт базу. Решение — ADR 0007.
"""

from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[2]

# Фабрика сессий: репозиторий берёт у неё сессию на один вызов — одну транзакцию.
Sessions = async_sessionmaker[AsyncSession]


class _DatabaseSettings(BaseSettings):
    """Читает переменные окружения и файл `.env`; остальные настройки из него пропускает."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # SecretStr: при печати настроек и в отчётах об ошибках вместо значения — звёздочки.
    database_url: SecretStr = SecretStr("")
    postgres_password: SecretStr = SecretStr("")


def database_url() -> URL:
    """Адрес базы. Пароль в тексте ошибок и в журнале не показывается."""
    settings = _DatabaseSettings()
    if settings.database_url.get_secret_value():
        try:
            url = make_url(settings.database_url.get_secret_value())
        except Exception:
            # `from None`: исходная ошибка несёт в себе адрес вместе с паролем.
            raise RuntimeError(
                "DATABASE_URL в файле .env записан с ошибкой. Ожидается "
                "postgresql+asyncpg://пользователь:пароль@адрес:порт/имя_базы"
            ) from None
        # Драйвер всегда asyncpg, даже если в адресе записано просто `postgresql://`.
        return url.set(drivername="postgresql+asyncpg")
    if settings.postgres_password.get_secret_value():
        return URL.create(
            "postgresql+asyncpg",
            username="platform",
            password=settings.postgres_password.get_secret_value(),
            host="localhost",
            port=5432,
            database="platform",
        )
    raise RuntimeError(
        "Не задан адрес базы: в файле .env нет ни DATABASE_URL, ни POSTGRES_PASSWORD. "
        "Образец — в .env.example."
    )


def make_engine(url: URL | None = None, **options: Any) -> AsyncEngine:
    return create_async_engine(url or database_url(), **options)


def make_sessions(engine: AsyncEngine) -> Sessions:
    # Записи остаются читаемыми и после закрытия сессии: репозиторий возвращает их наружу.
    return async_sessionmaker(engine, expire_on_commit=False)
