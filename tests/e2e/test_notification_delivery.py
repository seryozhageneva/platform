"""Подтверждение → настоящие инструменты MCP → подделки почты и Telegram."""

import asyncio
import json
import smtplib
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.models.connections import ConnectionRepository, SecretBox
from backend.models.users import UserRepository
from backend.triggers import mcp_blocks
from backend.triggers.assembly import Assembly
from backend.triggers.worker import run_manual
from mcp_servers.email.server import build_server as build_email
from mcp_servers.telegram.server import build_server as build_telegram

DEMO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/notifications-demo.json"
API = "/api/v1"
TELEGRAM_TOKEN = "12345:fake-demo_bot"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize("telegram_timeout", [False, True], ids=["delivery", "timeout"])
def test_only_approved_messages_reach_selected_channels(
    sessions, teacher, sample_docx, monkeypatch, telegram_timeout
):
    requests = []
    smtp = Mock()
    smtp.send_message.return_value = {}
    jobs = []

    def telegram_reply(request):
        assert request.url.path == f"/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.append(json.loads(request.content))
        if telegram_timeout:
            raise httpx.ReadTimeout("потерян ответ Telegram", request=request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    def telegram_child(name, *, url, token):
        assert name == "telegram" and url == "https://api.telegram.org"
        return build_telegram(token, transport=httpx.MockTransport(telegram_reply))

    async def enqueue(run_id):
        jobs.append(run_id)

    monkeypatch.setattr(mcp_blocks, "builtin_server", telegram_child)
    monkeypatch.setattr(mcp_blocks, "email_server", build_email)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Mock(return_value=smtp))
    monkeypatch.setenv("PLATFORM_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("PLATFORM_SMTP_PORT", "465")
    monkeypatch.setenv("PLATFORM_SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("PLATFORM_SMTP_PASSWORD", "fake-smtp-secret")
    monkeypatch.setenv("PLATFORM_SMTP_FROM", "sender@example.test")
    connections = ConnectionRepository(sessions, SecretBox(Fernet.generate_key().decode()))
    registry = load_registry(
        BUILTIN_BLOCKS,
        {
            "mcp": mcp_blocks.mcp_connector(
                mcp_blocks.connection_tools(connections), users=UserRepository(sessions)
            )
        },
    )
    assert registry.problems == []
    assembly = Assembly(sessions, registry, connections=connections)
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client = TestClient(
        create_app(assembly, enqueue=enqueue), headers={"Origin": "http://testserver"}
    )
    client.cookies.set(SESSION_COOKIE, session)

    connection = client.put(f"{API}/connections/telegram", json={"token": TELEGRAM_TOKEN})
    assert connection.status_code == 200, connection.text
    contacts = {
        "Telegram": {"telegram_id": 42, "email": "unused@example.test"},
        "Почта": {"email": "student@example.test"},
        "Кабинет": {},
        "Пропустить": {"telegram_id": 43, "email": "skip@example.test"},
    }
    student_ids = {}
    for name, values in contacts.items():
        student = client.post(f"{API}/students", json={"name": name})
        assert student.status_code == 201, student.text
        student_id = student.json()["id"]
        student_ids[name] = student_id
        saved = client.put(f"{API}/students/{student_id}/notification-contacts", json=values)
        assert saved.status_code == 200, saved.text

    uploaded = client.post(
        f"{API}/files",
        params={"name": "notification.docx"},
        headers={"Content-Type": DOCX},
        content=sample_docx,
    )
    assert uploaded.status_code == 201, uploaded.text
    saved = client.post(f"{API}/pipelines", json=json.loads(DEMO.read_text(encoding="utf-8")))
    assert saved.status_code == 201, saved.text
    assert saved.json()["warnings"] == []
    started = client.post(
        f"{API}/pipelines/{saved.json()['id']}/runs",
        json={"params": {"file_id": uploaded.json()["id"]}},
    )
    assert started.status_code == 201, started.text
    run_url = f"{API}/runs/{started.json()['id']}"
    [job] = jobs
    asyncio.run(run_manual(assembly, job))
    run = client.get(run_url).json()
    assert run["status"] == "waiting", run
    [waiting] = run["waiting"]
    smtp.send_message.assert_not_called()
    assert requests == []
    assert client.get(f"{API}/results").json() == []

    decisions = []
    for index, row in enumerate(waiting["data"]["rows"]):
        name = row["/student"]["name"]
        if name == "Пропустить" or (telegram_timeout and name != "Telegram"):
            decisions.append({"index": index, "keep": False})
        else:
            decisions.append({"index": index, "values": {"/message/text": f"Тест: {name}"}})
    approval = {
        "node_id": waiting["node_id"],
        "approval_id": waiting["approval_id"],
        "response": {"rows": decisions},
    }
    finished = client.post(f"{run_url}/responses", json=approval)
    assert finished.status_code == 200, finished.text
    assert client.post(f"{run_url}/responses", json=approval).status_code == 409
    assert requests == [{"chat_id": 42, "text": "Тест: Telegram"}]
    if telegram_timeout:
        assert finished.json()["status"] == "error", finished.text
        assert "Telegram не подтвердил отправку" in finished.json()["error"]
        smtp.send_message.assert_not_called()
        assert client.get(f"{API}/results").json() == []
        return

    assert finished.json()["status"] == "done", finished.text
    smtp.send_message.assert_called_once()
    args, kwargs = smtp.send_message.call_args
    assert kwargs["to_addrs"] == ["student@example.test"]
    assert args[0]["Subject"] == "Тестовая рекомендация"
    assert args[0].get_content().strip() == "Тест: Почта"
    [result] = client.get(f"{API}/results").json()
    assert result["student_id"] == student_ids["Кабинет"]
    assert result["content"]["text"] == "Тест: Кабинет"
