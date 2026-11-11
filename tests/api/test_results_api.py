"""Результаты кабинета и скачивание файлов через API на настоящих блоках (ADR 0027)."""

import pytest
from api_fakes import launch_and_read, saved

from backend.api.deps import SESSION_COOKIE
from backend.core.registry import BUILTIN_BLOCKS, load_registry

API = "/api/v1"
PDF = "application/pdf"

# Работа ученика -> её описание уходит в кабинет ученика, а отметка — преподавателю.
GRAPH = {
    "format": 1,
    "id": "results",
    "name": "Результаты в кабинеты",
    "params": [{"name": "work", "title": "Работа", "type": "string"}],
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "take",
            "type": "block",
            "block": "source.file",
            "config": {"file_id": {"$param": "work"}},
        },
        {
            "id": "to_student",
            "type": "block",
            "block": "sink.cabinet",
            "config": {"to": "recipient", "title": "Ваша работа принята"},
            "inputs": {"content": "take.file", "recipient": "take.file"},
        },
        {
            "id": "to_teacher",
            "type": "block",
            "block": "sink.cabinet",
            "config": {"title": "Работа получена"},
            "inputs": {"content": "take.file"},
        },
    ],
    "transitions": [
        {"from": "start", "to": "take"},
        {"from": "take", "when": "ok", "to": "to_student"},
        {"from": "to_student", "to": "to_teacher"},
    ],
}


@pytest.fixture
def client(client_of):
    return client_of(load_registry(BUILTIN_BLOCKS))


def student(client, teacher_headers, name):
    created = client.post(f"{API}/students", json={"name": name}, headers=teacher_headers)
    assert created.status_code == 201, created.text
    student_id = created.json()["id"]
    issued = client.post(f"{API}/students/{student_id}/link", headers=teacher_headers)
    signed_in = client.post(f"{API}/auth/student", json={"token": issued.json()["token"]})
    assert signed_in.status_code == 200, signed_in.text
    cookie = f"{SESSION_COOKIE}={signed_in.cookies[SESSION_COOKIE]}"
    return student_id, {"Cookie": cookie, "X-Expected-Account": student_id}


def upload(client, headers, student_id=None, name="работа.pdf"):
    params = {"name": name} | ({} if student_id is None else {"student_id": student_id})
    uploaded = client.post(
        f"{API}/files",
        params=params,
        headers={**headers, "Content-Type": PDF},
        content=b"%PDF-1.4 example",
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()


def delivered(client, headers, student_id):
    pipeline_id = saved(client, headers, GRAPH)
    work = upload(client, headers, student_id)
    run = launch_and_read(client, headers, pipeline_id, work=work["id"]).json()
    assert run["status"] == "done", run["error"]
    return run, work


def test_teacher_sees_own_results_and_student_only_theirs(client, me, stranger):
    owl, owl_headers = student(client, me, "Сова")
    fox, fox_headers = student(client, me, "Лиса")
    run, work = delivered(client, me, owl)

    teacher_view = client.get(f"{API}/results", headers=me).json()
    assert [(item["title"], item["student_name"]) for item in teacher_view] == [
        ("Работа получена", None),
        ("Ваша работа принята", "Сова"),
    ]
    assert teacher_view[1]["student_id"] == owl
    assert {item["run_id"] for item in teacher_view} == {run["id"]}
    assert teacher_view[1]["content"]["id"] == work["id"]

    [owl_view] = client.get(f"{API}/student/results", headers=owl_headers).json()
    assert owl_view["title"] == "Ваша работа принята"
    assert set(owl_view) == {"id", "title", "content", "created_at"}
    assert client.get(f"{API}/student/results", headers=fox_headers).json() == []
    assert client.get(f"{API}/results", headers=stranger).json() == []


def test_results_need_the_right_account(client, me):
    _, owl_headers = student(client, me, "Сова")
    client.cookies.clear()  # Вход ученика оставил сеанс в клиенте теста.
    assert client.get(f"{API}/results").status_code == 401
    assert client.get(f"{API}/student/results").status_code == 401
    assert client.get(f"{API}/results", headers=owl_headers).status_code == 403
    assert client.get(f"{API}/student/results", headers=me).status_code in {403, 422}


def test_own_file_is_downloaded_as_attachment(client, me, stranger):
    _, owl_headers = student(client, me, "Сова")
    file = upload(client, me, name='Лекция "1".pdf')
    url = f"{API}/files/{file['id']}/content"

    downloaded = client.get(url, headers=me)
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4 example"
    assert downloaded.headers["content-type"] == PDF
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    disposition = downloaded.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=\"file.pdf\"; filename*=UTF-8''")
    assert '"1"' not in disposition

    assert client.get(url, headers=stranger).status_code == 404
    assert client.get(url, headers=owl_headers).status_code == 403
    client.cookies.clear()  # Вход ученика оставил сеанс в клиенте теста.
    assert client.get(url).status_code == 401
    missing = f"{API}/files/00000000-0000-0000-0000-000000000000/content"
    assert client.get(missing, headers=me).status_code == 404
