"""Сеансы, проверка источника и управление ученическими ссылками."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update

from backend.api.deps import SESSION_COOKIE
from backend.api.passwords import hash_password
from backend.models.auth import AuthRepository
from backend.models.tables import LoginSessionRow, UserRow

API = "/api/v1"
PASSWORD = "выдуманный-пароль"


def test_teacher_login_and_logout(client, teacher, sessions):
    assert asyncio.run(
        AuthRepository(sessions).set_initial_password(teacher.id, hash_password(PASSWORD))
    )
    login = f"{API}/auth/teacher"
    wrong = client.post(login, json={"email": teacher.email, "password": "wrong"})
    unknown = client.post(login, json={"email": "nobody@example.test", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    received = client.post(login, json={"email": teacher.email.upper(), "password": PASSWORD})
    assert received.status_code == 200
    assert "HttpOnly" in received.headers["set-cookie"]
    assert received.json()["role"] == "teacher"
    assert client.get(f"{API}/auth/me").json()["id"] == str(teacher.id)
    copied_cookie = client.cookies[SESSION_COOKIE]
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 401
    assert (
        client.get(
            f"{API}/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={copied_cookie}"}
        ).status_code
        == 401
    )


def test_expired_session_and_cross_origin(client, me, sessions):
    denied = client.post(
        f"{API}/students", json={"name": "Ученик"}, headers={**me, "Origin": "https://else.test"}
    )
    assert denied.status_code == 403
    assert client.get(f"{API}/students", headers=me).json() == []

    async def expire():
        async with sessions.begin() as db:
            await db.execute(update(LoginSessionRow).values(expires_at=datetime.now(UTC)))

    asyncio.run(expire())
    assert client.get(f"{API}/auth/me", headers=me).status_code == 401


def test_reissue_and_revoke_links(client, me, stranger):
    students = f"{API}/students"
    created = client.post(students, json={"name": "Сова"}, headers=me)
    assert created.status_code == 201
    student = created.json()
    link = f"{students}/{student['id']}/link"
    assert client.get(students, headers=stranger).json() == []
    assert client.post(link, headers=stranger).status_code == 404
    assert client.delete(link, headers=stranger).status_code == 404
    issued = client.post(link, headers=me)
    assert issued.status_code == 200
    first = issued.json()["token"]
    assert first not in client.get(students, headers=me).text
    login = f"{API}/auth/student"

    with (
        TestClient(client.app, headers=client.headers) as one,
        TestClient(client.app, headers=client.headers) as two,
    ):
        assert one.post(login, json={"token": first}).status_code == 200
        assert two.post(login, json={"token": first}).status_code == 200
        assert one.get(f"{API}/auth/me").json()["id"] == student["id"]
        assert one.get(f"{API}/tasks").status_code == 403

        second = client.post(link, headers=me).json()["token"]
        assert one.post(login, json={"token": first}).status_code == 401
        assert one.get(f"{API}/auth/me").status_code == 401
        assert two.get(f"{API}/auth/me").status_code == 401

        assert one.post(login, json={"token": second}).status_code == 200
        assert two.post(login, json={"token": second}).status_code == 200
        assert client.delete(link, headers=me).status_code == 204
        assert one.get(f"{API}/auth/me").status_code == 401
        assert two.get(f"{API}/auth/me").status_code == 401
        assert two.post(login, json={"token": second}).status_code == 401


def test_expired_link(client, me, sessions):
    student = client.post(f"{API}/students", json={"name": "Ёж"}, headers=me).json()
    issued = client.post(f"{API}/students/{student['id']}/link", headers=me).json()

    async def expire():
        async with sessions.begin() as db:
            await db.execute(
                update(UserRow)
                .where(UserRow.role == "student")
                .values(link_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )

    asyncio.run(expire())
    assert client.post(f"{API}/auth/student", json={"token": issued["token"]}).status_code == 401


def test_stale_teacher_screen_cannot_write_under_a_different_session(client, teacher, me, stranger):
    students = f"{API}/students"
    stale = {**stranger, "X-Expected-Account": str(teacher.id)}

    assert client.get(students, headers=stale).status_code == 409
    assert client.post(students, headers=stale, json={"name": "Сова"}).status_code == 409
    assert client.get(students, headers=stranger).json() == []

    current = {**me, "X-Expected-Account": str(teacher.id)}
    assert client.post(students, headers=current, json={"name": "Сова"}).status_code == 201


def test_invalid_unicode_is_rejected_at_login(client):
    cases = [
        ("teacher", "password", rb'{"email":"a@example.test","password":"\ud800"}'),
        ("teacher", "email", rb'{"email":"\ud800","password":"demo"}'),
        ("student", "token", rb'{"token":"\ud800"}'),
    ]
    for role, field, body in cases:
        refused = client.post(
            f"{API}/auth/{role}", content=body, headers={"Content-Type": "application/json"}
        )
        assert refused.status_code == 422
        assert refused.json()["problems"][0]["message"].startswith(f"{field}:")
