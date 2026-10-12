"""Адрес базы: собирается из настроек, а пароль не попадает в сообщения об ошибках."""

import pytest

from backend.models.db import _DatabaseSettings, database_url

PASSWORD = "vydumannyi-parol"


def test_address_is_built_from_the_compose_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", PASSWORD)

    url = database_url()

    assert (url.drivername, url.host, url.port) == ("postgresql+asyncpg", "localhost", 5432)
    assert (url.username, url.database, url.password) == ("platform", "platform", PASSWORD)


def test_explicit_address_wins_and_always_uses_asyncpg(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql://teacher:{PASSWORD}@db.example.test:6543/school"
    )
    monkeypatch.setenv("POSTGRES_PASSWORD", "drugoi")

    url = database_url()

    assert (url.drivername, url.host, url.port) == ("postgresql+asyncpg", "db.example.test", 6543)
    assert (url.database, url.password) == ("school", PASSWORD)


def test_password_is_hidden_when_settings_or_address_are_printed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://teacher:{PASSWORD}@localhost:5432/school")
    monkeypatch.setenv("POSTGRES_PASSWORD", PASSWORD)

    assert PASSWORD not in repr(_DatabaseSettings())
    assert PASSWORD not in str(database_url())
    assert PASSWORD not in repr(database_url())


def test_broken_address_is_explained_without_showing_it(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://teacher:{PASSWORD}@localhost:port/school")

    with pytest.raises(RuntimeError, match="DATABASE_URL в файле .env записан с ошибкой") as caught:
        database_url()

    assert PASSWORD not in str(caught.value)
    # Исходная ошибка с адресом внутри к новой не прицеплена.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
