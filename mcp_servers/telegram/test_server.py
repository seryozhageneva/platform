import asyncio
import json

import httpx
import pytest
from mcp import Client

from mcp_servers.telegram.server import build_server

TOKEN = "12345:fake-test_bot"


def _send(transport, *, chat_id=12345, text="Повтори дроби."):
    async def send():
        async with Client(build_server(TOKEN, transport=transport)) as client:
            [tool] = (await client.list_tools()).tools
            assert tool.annotations is not None and tool.annotations.read_only_hint is False
            return await client.call_tool("send_message", {"chat_id": chat_id, "text": text})

    return asyncio.run(send())


def test_send_message_uses_bot_api_and_plain_text():
    def reply(request):
        assert request.method == "POST"
        assert request.url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        assert json.loads(request.content) == {"chat_id": 12345, "text": "Повтори дроби."}
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})

    result = _send(httpx.MockTransport(reply))
    assert not result.is_error and result.structured_content == {"outcome": "sent"}


@pytest.mark.parametrize("status", [200, 403, 429])
def test_telegram_refusal_does_not_return_external_text_or_token(status):
    def reply(request):
        return httpx.Response(status, json={"ok": False, "description": TOKEN})

    result = _send(httpx.MockTransport(reply))
    assert result.is_error and "не подтвердил" in str(result.content)
    assert TOKEN not in str(result.content)


@pytest.mark.parametrize("chat_id,text", [(-12345, "Привет"), (12345, "x" * 4097)])
def test_invalid_message_is_rejected_locally(chat_id, text):
    def unexpected(request):
        pytest.fail("некорректное сообщение не должно попасть в Telegram")

    assert _send(httpx.MockTransport(unexpected), chat_id=chat_id, text=text).is_error
