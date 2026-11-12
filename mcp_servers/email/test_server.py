import asyncio
import smtplib
from unittest.mock import Mock

import pytest
from mcp import Client

from mcp_servers.email.server import build_server

SETTINGS = {
    "SMTP_HOST": "smtp.example.test",
    "SMTP_PORT": "465",
    "SMTP_USERNAME": "test@example.test",
    "SMTP_PASSWORD": "fake-secret",
    "SMTP_FROM": "sender@example.test",
}
RECIPIENT = "student@example.test"


@pytest.mark.parametrize("port", [465, 587])
def test_send_email_uses_tls_and_one_recipient(monkeypatch, port):
    smtp = Mock()
    smtp.send_message.return_value = {}
    constructor = Mock(return_value=smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL" if port == 465 else "SMTP", constructor)

    async def send():
        async with Client(build_server({**SETTINGS, "SMTP_PORT": str(port)})) as client:
            [tool] = (await client.list_tools()).tools
            assert tool.annotations is not None and tool.annotations.read_only_hint is False
            return await client.call_tool(
                "send_email", {"email": RECIPIENT, "subject": "Дроби", "text": "Повтори дроби."}
            )

    result = asyncio.run(send())
    assert not result.is_error and result.structured_content == {"outcome": "sent"}
    assert constructor.call_args.args == (SETTINGS["SMTP_HOST"], port)
    if port == 587:
        assert [call[0] for call in smtp.method_calls] == [
            "starttls",
            "login",
            "send_message",
            "close",
        ]
        tls = smtp.starttls.call_args.kwargs["context"]
    else:
        smtp.starttls.assert_not_called()
        tls = constructor.call_args.kwargs["context"]
    assert tls.check_hostname
    smtp.login.assert_called_once_with(SETTINGS["SMTP_USERNAME"], SETTINGS["SMTP_PASSWORD"])
    (message,), kwargs = smtp.send_message.call_args
    assert kwargs == {"from_addr": SETTINGS["SMTP_FROM"], "to_addrs": [RECIPIENT]}
    assert message["To"] == RECIPIENT and message["Subject"] == "Дроби"
    assert message.get_content().strip() == "Повтори дроби."


def test_smtp_failure_does_not_return_credentials(monkeypatch):
    smtp = Mock()
    smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"fake-secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", Mock(return_value=smtp))

    async def send():
        async with Client(build_server(SETTINGS)) as client:
            return await client.call_tool("send_email", {"email": RECIPIENT, "text": "Текст"})

    result = asyncio.run(send())
    assert result.is_error
    assert "не подтвердил" in str(result.content)
    assert SETTINGS["SMTP_PASSWORD"] not in str(result.content)
    smtp.send_message.assert_not_called()
    smtp.close.assert_called_once()
