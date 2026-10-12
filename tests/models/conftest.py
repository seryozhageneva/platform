"""Общее для тестов базы: отдельная тестовая база, миграции и чистые таблицы в каждом тесте.

Тесты идут на базе `platform_test` в том же контейнере PostgreSQL: она создаётся перед
тестами и удаляется после. Рабочая база `platform` не затрагивается. Данные — выдуманные.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from backend.models.db import Sessions, database_url, make_engine, make_sessions
from backend.models.tables import Base, UserRow
from backend.models.users import UserRepository

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = "platform_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


async def _execute(url: URL, *statements: str) -> None:
    # AUTOCOMMIT: создать и удалить базу внутри транзакции нельзя.
    engine = make_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[URL]:
    """Пустая тестовая база рядом с рабочей."""
    try:
        working = database_url()
    except RuntimeError as error:
        pytest.fail(str(error), pytrace=False)
    if working.host not in LOCAL_HOSTS:
        pytest.fail(
            "Тесты базы запускаются только на своём компьютере: адрес базы в .env указывает "
            "на другой сервер.",
            pytrace=False,
        )
    assert working.database != TEST_DB, "рабочая база не может называться как тестовая"
    service = working.set(database="postgres")
    drop = f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'
    try:
        asyncio.run(_execute(service, drop, f'CREATE DATABASE "{TEST_DB}"'))
    except (OSError, DBAPIError) as error:
        pytest.fail(
            "База данных не отвечает. Подними её командой: docker compose up -d --wait\n"
            f"({type(error).__name__})",
            pytrace=False,
        )
    yield working.set(database=TEST_DB)
    asyncio.run(_execute(service, drop))


@pytest.fixture(scope="session")
def alembic_config(test_db_url: URL) -> Config:
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "models" / "migrations"))
    config.attributes["url"] = test_db_url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def migrated(alembic_config: Config) -> None:
    """Все миграции применены к пустой базе — это и есть проверка «на чистой БД»."""
    command.upgrade(alembic_config, "head")


@pytest.fixture
def sessions(test_db_url: URL, migrated: None) -> Iterator[Sessions]:
    """Фабрика сессий для репозиториев; после теста таблицы очищаются."""
    # NullPool: каждый `asyncio.run` в тесте открывает свои соединения и сам их закрывает.
    engine = make_engine(test_db_url, poolclass=NullPool)
    yield make_sessions(engine)
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    asyncio.run(_execute(test_db_url, f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def teacher(sessions: Sessions) -> UserRow:
    return asyncio.run(
        UserRepository(sessions).create_teacher(name="Преподаватель А", email="a@example.test")
    )


@pytest.fixture
def other_teacher(sessions: Sessions) -> UserRow:
    return asyncio.run(
        UserRepository(sessions).create_teacher(name="Преподаватель Б", email="b@example.test")
    )
