"""Отправка текстового сообщения в личный чат Telegram (ADR 0033)."""

from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations


def build_server(token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    server = MCPServer("telegram")

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=False, open_world_hint=True
        )
    )
    async def send_message(chat_id: int, text: str) -> dict[str, Literal["sent"]]:
        """Отправить текст в личный чат, где получатель уже открыл диалог с ботом."""
        if not 0 < chat_id < 2**52:
            raise ToolError("нужен номер личного чата Telegram")
        if not text.strip() or len(text) > 4096:
            raise ToolError("нужен текст сообщения длиной от 1 до 4096 символов")
        if not token:
            raise ToolError("не настроен токен бота Telegram")
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=10, trust_env=False
            ) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError):
            raise ToolError("Telegram не подтвердил отправку сообщения") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ToolError("Telegram не подтвердил отправку сообщения")
        return {"outcome": "sent"}

    return server
