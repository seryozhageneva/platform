"""Загрузка документов и проверка прав через API преподавателя."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from backend.api import files

PATH = "/api/v1/files"
PDF = "application/pdf"


def test_teacher_uploads_a_file(client, me, teacher, sample_pdf):
    response = client.post(
        PATH, params={"name": "Лекция.pdf"}, headers={**me, "Content-Type": PDF}, content=sample_pdf
    )
    assert response.status_code == 201, response.text
    file = response.json()
    assert file["name"] == "Лекция.pdf"
    assert file["kind"] == "document"
    assert file["media_type"] == PDF
    assert file["size"] == len(sample_pdf)
    assert file["student_id"] is None
    stored = asyncio.run(client.app.state.assembly.files.read(teacher.id, UUID(file["id"])))
    assert stored == sample_pdf


def test_only_a_teachers_own_student_can_be_associated_with_a_file(client, me, stranger):
    students = "/api/v1/students"
    own = client.post(students, json={"name": "Сова"}, headers=me).json()["id"]
    other = client.post(students, json={"name": "Лиса"}, headers=stranger).json()["id"]

    def upload(student_id):
        return client.post(
            PATH,
            params={"name": "Работа.pdf", "student_id": student_id},
            headers={**me, "Content-Type": PDF},
            content=b"document",
        )

    accepted = upload(own)
    assert accepted.status_code == 201
    assert accepted.json()["student_id"] == own
    assert upload(other).status_code == 404
    assert upload(str(uuid4())).status_code == 404


def test_student_cannot_upload(client, me):
    students = "/api/v1/students"
    student = client.post(students, json={"name": "Сова"}, headers=me).json()["id"]
    token = client.post(f"{students}/{student}/link", headers=me).json()["token"]
    assert client.post("/api/v1/auth/student", json={"token": token}).status_code == 200
    response = client.post(
        PATH, params={"name": "Работа.pdf"}, headers={"Content-Type": PDF}, content=b"document"
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("media_type", "content", "name", "status"),
    [
        (PDF, b"", "file.pdf", 422),
        ("text/plain", b"text", "file.txt", 415),
        (PDF, b"document", "   ", 422),
    ],
)
def test_refuses_invalid_upload(client, me, media_type, content, name, status):
    response = client.post(
        PATH, params={"name": name}, headers={**me, "Content-Type": media_type}, content=content
    )
    assert response.status_code == status


def test_limits_actual_stream_and_stops_reading(client, me, monkeypatch):
    monkeypatch.setattr(files, "MAX_FILE_SIZE", 4)

    async def chunks():
        yield b"1234"
        yield b"5"
        pytest.fail("сервер запросил ещё одну часть после превышения лимита")

    async def upload():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as http:
            headers = {**me, "Origin": "http://testserver", "Content-Type": PDF}
            accepted = await http.post(
                PATH, params={"name": "file.pdf"}, headers=headers, content=b"1234"
            )
            rejected = await http.post(
                PATH, params={"name": "file.pdf"}, headers=headers, content=chunks()
            )
        assert accepted.status_code == 201
        assert rejected.status_code == 413

    asyncio.run(upload())
