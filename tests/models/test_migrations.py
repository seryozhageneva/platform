"""Миграции: применяются на чистой базе, совпадают с описанием таблиц и откатываются."""

import asyncio

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.pool import NullPool

from backend.models.db import make_engine

TABLES = {
    "users",
    "groups",
    "group_members",
    "tasks",
    "pipelines",
    "pipeline_versions",
    "assignments",
    "runs",
    "events",
    "llm_calls",
    "submissions",
}


def table_names(url) -> set[str]:
    async def read() -> set[str]:
        engine = make_engine(url, poolclass=NullPool)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        await engine.dispose()
        return set(names)

    return asyncio.run(read())


def test_migrations_create_all_tables_on_clean_database(test_db_url, migrated):
    assert table_names(test_db_url) == TABLES | {"alembic_version"}


def test_tables_and_migrations_agree(alembic_config, migrated):
    """Если таблицу поправили в коде, а миграцию не написали, `alembic check` падает."""
    command.check(alembic_config)


def test_migrations_roll_back_and_apply_again(test_db_url, alembic_config, migrated):
    command.downgrade(alembic_config, "base")
    assert table_names(test_db_url) == {"alembic_version"}

    command.upgrade(alembic_config, "head")
    assert table_names(test_db_url) == TABLES | {"alembic_version"}
