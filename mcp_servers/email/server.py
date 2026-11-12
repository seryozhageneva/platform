"""Отправка текстового письма через почтовый ящик платформы (ADR 0033)."""

import asyncio
import smtplib
import ssl
from collections.abc import Mapping
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations


def build_server(settings: Mapping[str, str]) -> MCPServer:
    server = MCPServer("email")

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=False, open_world_hint=True
        )
    )
    async def send_email(
        email: str, text: str, subject: str = "Рекомендация"
    ) -> dict[str, Literal["sent"]]:
        """Отправить одно текстовое письмо. Почтовый сервер принимает письмо к доставке."""
        if not text.strip() or len(text) > 65_536 or "\x00" in text:
            raise ToolError("нужен текст письма длиной от 1 до 65536 символов")
        if not subject.strip() or len(subject) > 200 or any(char in subject for char in "\r\n\x00"):
            raise ToolError("нужна тема письма длиной от 1 до 200 символов в одну строку")
        try:
            await asyncio.to_thread(_send, settings, email, subject, text)
        except (HeaderParseError, KeyError, ValueError, OSError):
            raise ToolError("почтовый сервер не подтвердил отправку письма") from None
        return {"outcome": "sent"}

    return server


def _send(settings: Mapping[str, str], email: str, subject: str, text: str) -> None:
    message = EmailMessage()
    sender = Address(addr_spec=settings["SMTP_FROM"])
    recipient = Address(addr_spec=email)
    if not all(address.username and address.domain for address in (sender, recipient)):
        raise ValueError("нужны одиночные адреса отправителя и получателя")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    host, port = settings["SMTP_HOST"], int(settings["SMTP_PORT"])
    tls = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=10, context=tls)
    elif port == 587:
        smtp = smtplib.SMTP(host, port, timeout=10)
    else:
        raise ValueError("неизвестный режим TLS")
    try:
        if port == 587:
            smtp.starttls(context=tls)
        smtp.login(settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
        refused = smtp.send_message(
            message, from_addr=sender.addr_spec, to_addrs=[recipient.addr_spec]
        )
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        smtp.close()
