"""Сервер за посредником (Caddy на VPS, ADR 0030).

Браузер приходит к Caddy по HTTPS, а Caddy к API — по обычному HTTP внутри Docker. О том, что
снаружи был HTTPS, API узнаёт из заголовка `X-Forwarded-Proto`. Без этого вход ломается:
проверка источника ждёт `http://…`, а браузер присылает `Origin: https://…`. Верить заголовку
можно только посреднику: иначе любой клиент назвал бы свой HTTP «защищённым».
"""

import asyncio

from fastapi.testclient import TestClient

from backend.api.__main__ import ServerSettings, server_config
from backend.api.passwords import hash_password
from backend.models.auth import AuthRepository

API = "/api/v1"
PASSWORD = "выдуманный-пароль"
SITE = "https://platform.example.test"


def _behind(client: TestClient, trusted: str) -> TestClient:
    """Тот же сервер, но так, как его запускает `python -m backend.api`."""
    config = server_config(client.app, ServerSettings(api_host="0.0.0.0", trusted_proxies=trusted))
    config.load()
    # TestClient называет адрес клиента «testclient»: в тесте это адрес посредника.
    return TestClient(config.loaded_app, base_url="http://platform.example.test")


def _login(client: TestClient, teacher):
    return client.post(
        f"{API}/auth/teacher",
        json={"email": teacher.email, "password": PASSWORD},
        headers={"Origin": SITE, "X-Forwarded-Proto": "https"},
    )


def _set_password(sessions, teacher) -> None:
    assert asyncio.run(
        AuthRepository(sessions).set_initial_password(teacher.id, hash_password(PASSWORD))
    )


def test_login_through_trusted_proxy_gets_secure_cookie(client, teacher, sessions):
    _set_password(sessions, teacher)
    with _behind(client, trusted="testclient") as proxied:
        received = _login(proxied, teacher)

    assert received.status_code == 200
    cookie = received.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie


def test_forwarded_header_from_stranger_is_ignored(client, teacher, sessions):
    _set_password(sessions, teacher)
    with _behind(client, trusted="127.0.0.1") as direct:
        received = _login(direct, teacher)

    # Заголовок не принят: сервер считает запрос HTTP, а источник HTTPS — чужим сайтом.
    assert received.status_code == 403


def test_defaults_listen_only_on_this_computer(monkeypatch):
    # Как в .env.example: переменные есть, но пустые.
    monkeypatch.setenv("PLATFORM_API_HOST", "")
    monkeypatch.setenv("PLATFORM_TRUSTED_PROXIES", "")
    settings = ServerSettings(_env_file=None)

    assert settings.api_host == "127.0.0.1"
    assert settings.trusted_proxies == "127.0.0.1"
