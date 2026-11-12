import asyncio
from uuid import UUID

import pytest

from backend.models.users import UserRepository


def test_contacts_can_be_set_and_cleared_only_by_own_teacher(client, me, stranger, sessions):
    created = client.post("/api/v1/students", json={"name": "Ученик А"}, headers=me)
    assert created.status_code == 201, created.text
    student_id = created.json()["id"]
    path = f"/api/v1/students/{student_id}/notification-contacts"
    contacts = {"email": "student@example.test", "telegram_id": 1_000_000_001}
    assert client.put(path, json=contacts).status_code == 401
    assert client.put(path, json=contacts, headers=stranger).status_code == 404
    saved = client.put(path, json=contacts, headers=me)
    assert saved.status_code == 200, saved.text
    assert saved.json() == contacts

    row = asyncio.run(UserRepository(sessions).get(UUID(student_id)))
    assert row is not None and row.email is None
    assert (
        row.notification_email == contacts["email"] and row.telegram_id == contacts["telegram_id"]
    )
    assert client.get("/api/v1/students", headers=me).json() == [created.json()]
    cleared = client.put(path, json={}, headers=me)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"email": None, "telegram_id": None}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "one@example.test,two@example.test"},
        {"email": "Ученик <student@example.test>"},
        {"telegram_id": -1234},
        {"telegram_id": True},
        {"telegram_id": 2**52},
    ],
)
def test_invalid_contacts_are_refused(client, me, teacher, sessions, body):
    student = asyncio.run(UserRepository(sessions).create_student(teacher.id, name="Ученик"))
    path = f"/api/v1/students/{student.id}/notification-contacts"
    assert client.put(path, json=body, headers=me).status_code == 422
