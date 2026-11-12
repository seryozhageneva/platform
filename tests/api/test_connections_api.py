"""API подключений: токен не возвращается, чужое не видно, без ключа — понятный отказ."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.models.connections import ConnectionRepository, SecretBox
from backend.triggers.assembly import Assembly

TOKEN = "0123456789abcdef0123456789abcdef"
MOODLE = {"url": "https://moodle.example.test/", "token": TOKEN}


@pytest.fixture
def api(sessions, registry_of) -> TestClient:
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    return TestClient(
        create_app(Assembly(sessions, registry_of(), connections=connections)),
        headers={"Origin": "http://testserver"},
    )


def test_save_list_and_delete_without_token_in_answers(api, me):
    saved = api.put("/api/v1/connections/moodle", json=MOODLE, headers=me)
    assert saved.status_code == 200, saved.text
    assert saved.json()["url"] == "https://moodle.example.test"
    assert saved.json()["kind"] == "moodle"
    listed = api.get("/api/v1/connections", headers=me)
    assert [item["url"] for item in listed.json()] == ["https://moodle.example.test"]
    assert TOKEN not in saved.text + listed.text

    assert api.delete("/api/v1/connections/moodle", headers=me).status_code == 204
    assert api.get("/api/v1/connections", headers=me).json() == []
    assert api.delete("/api/v1/connections/moodle", headers=me).status_code == 404


def test_other_teacher_does_not_see_or_delete(api, me, stranger):
    api.put("/api/v1/connections/moodle", json=MOODLE, headers=me)
    assert api.get("/api/v1/connections", headers=stranger).json() == []
    assert api.delete("/api/v1/connections/moodle", headers=stranger).status_code == 404
    assert len(api.get("/api/v1/connections", headers=me).json()) == 1


def test_telegram_uses_fixed_address_and_keeps_token_private(api, me, stranger):
    token = "12345:fake-test_bot"
    saved = api.put("/api/v1/connections/telegram", json={"token": token}, headers=me)
    assert saved.status_code == 200, saved.text
    assert saved.json()["url"] == "https://api.telegram.org"
    assert saved.json()["kind"] == "telegram"
    listed = api.get("/api/v1/connections", headers=me)
    assert token not in saved.text + listed.text
    assert api.get("/api/v1/connections", headers=stranger).json() == []

    for body in ({"token": "bad-token"}, {"url": "https://example.test", "token": token}):
        answer = api.put("/api/v1/connections/telegram", json=body, headers=me)
        assert answer.status_code == 422, answer.text
        assert body["token"] not in answer.text


def test_without_login_nothing_is_available(api):
    assert api.get("/api/v1/connections").status_code == 401
    assert api.put("/api/v1/connections/moodle", json=MOODLE).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"url": "ftp://moodle.example.test", "token": TOKEN},
        {"url": "https://moodle.example.test/?a=1", "token": TOKEN},
        {"url": "https://admin:pass@moodle.example.test", "token": TOKEN},
        {"url": "https://moodle.example.test", "token": ""},
        {"url": "https://moodle.example.test", "token": "abc&wsfunction=x"},
    ],
)
def test_bad_connection_is_refused_without_echoing_token(api, me, body):
    answer = api.put("/api/v1/connections/moodle", json=body, headers=me)
    assert answer.status_code == 422
    if body["token"]:
        assert body["token"] not in answer.text


def test_unknown_kind_is_refused(api, me):
    assert api.put("/api/v1/connections/gmail", json=MOODLE, headers=me).status_code == 422


def test_without_secret_key_connections_are_unavailable(client, me):
    answer = client.put("/api/v1/connections/moodle", json=MOODLE, headers=me)
    assert answer.status_code == 503
    assert "PLATFORM_SECRET_KEY" in answer.json()["message"]
