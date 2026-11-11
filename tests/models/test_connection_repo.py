"""Подключения: токен в базе только зашифрован, чужое подключение не видно (ADR 0028)."""

import asyncio

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from backend.models.connections import ConnectionRepository, SecretBox
from backend.models.tables import ConnectionKind, ConnectionRow

TOKEN = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(Fernet.generate_key().decode())


def test_token_is_stored_only_encrypted(sessions, teacher, box):
    async def scenario():
        repo = ConnectionRepository(sessions, box)
        await repo.save(teacher.id, ConnectionKind.MOODLE, url="http://moodle.test", token=TOKEN)
        async with sessions() as session:
            row = await session.scalar(select(ConnectionRow))
        assert TOKEN.encode() not in row.token_encrypted
        assert row.url == "http://moodle.test"
        found = await repo.credentials(teacher.id, ConnectionKind.MOODLE)
        assert (found.url, found.token) == ("http://moodle.test", TOKEN)
        assert TOKEN not in repr(found)

    asyncio.run(scenario())


def test_save_again_replaces_connection(sessions, teacher, box):
    async def scenario():
        repo = ConnectionRepository(sessions, box)
        first = await repo.save(teacher.id, ConnectionKind.MOODLE, url="http://a.test", token="a1")
        second = await repo.save(teacher.id, ConnectionKind.MOODLE, url="http://b.test", token="b2")
        assert second.id == first.id
        assert [row.url for row in await repo.list(teacher.id)] == ["http://b.test"]
        assert (await repo.credentials(teacher.id, ConnectionKind.MOODLE)).token == "b2"

    asyncio.run(scenario())


def test_other_teacher_does_not_see_connection(sessions, teacher, other_teacher, box):
    async def scenario():
        repo = ConnectionRepository(sessions, box)
        await repo.save(teacher.id, ConnectionKind.MOODLE, url="http://moodle.test", token=TOKEN)
        assert await repo.credentials(other_teacher.id, ConnectionKind.MOODLE) is None
        assert await repo.list(other_teacher.id) == []
        assert await repo.delete(other_teacher.id, ConnectionKind.MOODLE) is False
        assert await repo.delete(teacher.id, ConnectionKind.MOODLE) is True
        assert await repo.credentials(teacher.id, ConnectionKind.MOODLE) is None

    asyncio.run(scenario())


def test_changed_key_is_clear_error(sessions, teacher, box):
    async def scenario():
        await ConnectionRepository(sessions, box).save(
            teacher.id, ConnectionKind.MOODLE, url="http://moodle.test", token=TOKEN
        )
        other = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
        with pytest.raises(RuntimeError, match="ключ PLATFORM_SECRET_KEY сменился"):
            await other.credentials(teacher.id, ConnectionKind.MOODLE)

    asyncio.run(scenario())


def test_bad_or_missing_key(monkeypatch):
    with pytest.raises(RuntimeError, match="записан с ошибкой") as error:
        SecretBox("not-a-key")
    assert "not-a-key" not in str(error.value)
    monkeypatch.setenv("PLATFORM_SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="Не задан PLATFORM_SECRET_KEY"):
        SecretBox.from_env()
