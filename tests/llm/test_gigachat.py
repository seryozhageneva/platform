"""Провайдер GigaChat: что уходит в библиотеку и как её ответы и ошибки доходят до слоя.

Настоящего GigaChat здесь нет: вместо клиента библиотеки подставлена подделка.
"""

import asyncio
import ssl
from pathlib import Path

import httpx
import pytest
from gigachat.exceptions import AuthenticationError, RateLimitError, ServerError
from gigachat.models import ChatCompletion

from backend.core.contracts.interfaces import LLMMessage
from backend.core.contracts.ports import FileKind, FileRef
from backend.llm.gigachat import GigaChatProvider
from backend.llm.providers import LLMError

AUTH_KEY = "выдуманный-ключ-для-теста"
ASK = [
    LLMMessage(role="system", content="Ты учитель математики."),
    LLMMessage(role="user", content="Сколько будет 2 + 2?"),
]


def completion(text: str = "4", model: str = "GigaChat-2:2.0.28.2") -> ChatCompletion:
    """Ответ в том виде, в каком его возвращает библиотека."""
    return ChatCompletion.model_validate(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "created": 1791878400,
            "model": model,
            "usage": {"prompt_tokens": 21, "completion_tokens": 1, "total_tokens": 22},
            "object": "chat.completion",
        }
    )


class FakeSdkClient:
    """Подделка клиента библиотеки `gigachat`: запоминает запрос, отвечает заданным."""

    def __init__(self, reply: ChatCompletion | Exception) -> None:
        self.reply = reply
        self.payloads = []
        self.closed = False

    async def achat(self, payload):
        self.payloads.append(payload)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def aclose(self) -> None:
        self.closed = True


def provider(reply: ChatCompletion | Exception) -> tuple[GigaChatProvider, FakeSdkClient]:
    client = FakeSdkClient(reply)
    made = GigaChatProvider(
        auth_key=AUTH_KEY,
        scope="GIGACHAT_API_PERS",
        model="GigaChat-2",
        ca_bundle_file=Path("certs/russian_trusted_root_ca.cer"),
        client=client,
    )
    return made, client


def chat(made: GigaChatProvider, messages=ASK, **options):
    return asyncio.run(made.chat(messages, **options))


def failure(reply: Exception) -> LLMError:
    made, _ = provider(reply)
    with pytest.raises(LLMError) as caught:
        chat(made)
    return caught.value


def response_error(kind: type, status: int) -> Exception:
    return kind("https://example.test/chat/completions", status, b"{}", None)


def test_roles_text_and_default_model_go_into_the_request():
    made, client = provider(completion())

    chat(made)

    (payload,) = client.payloads
    assert payload.model == "GigaChat-2"
    assert [(message.role, message.content) for message in payload.messages] == [
        ("system", "Ты учитель математики."),
        ("user", "Сколько будет 2 + 2?"),
    ]


def test_block_can_ask_for_another_model():
    made, client = provider(completion())

    chat(made, model="GigaChat-2-Max")

    assert client.payloads[0].model == "GigaChat-2-Max"


def test_reply_becomes_text_model_and_tokens():
    made, _ = provider(completion("4"))

    reply = chat(made)

    assert reply.text == "4"
    assert reply.model == "GigaChat-2:2.0.28.2"
    assert (reply.input_tokens, reply.output_tokens) == (21, 1)


def test_rejected_key_is_explained_without_showing_the_key():
    error = failure(response_error(AuthenticationError, 401))

    assert error.kind == "auth"
    assert "GIGACHAT_AUTH_KEY" in str(error)
    assert AUTH_KEY not in str(error)
    # Исходная ошибка библиотеки несёт адрес и заголовки — к нашей она не прицеплена.
    assert error.__cause__ is None


def test_rate_limit_is_explained():
    assert failure(response_error(RateLimitError, 429)).kind == "rate_limit"


def test_server_error_keeps_only_the_status_code():
    error = failure(response_error(ServerError, 503))

    assert error.kind == "provider"
    assert str(error) == "GigaChat ответил ошибкой 503"


def test_timeout_is_explained():
    error = failure(httpx.ReadTimeout("timed out"))

    assert error.kind == "timeout"
    assert "не ответил за 60 секунд" in str(error)


def test_certificate_problem_points_at_the_setting():
    error = failure(httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer"))

    assert error.kind == "certificate"
    assert "GIGACHAT_CA_BUNDLE_FILE" in str(error)


def test_file_that_is_not_a_certificate_is_explained():
    error = failure(ssl.SSLError("[X509: NO_CERTIFICATE_OR_CRL_FOUND] no certificate or crl found"))

    assert error.kind == "certificate"
    assert "BEGIN CERTIFICATE" in str(error)


def test_no_connection_is_explained():
    assert failure(httpx.ConnectError("Name or service not known")).kind == "network"


def test_empty_reply_is_an_error():
    empty = completion()
    empty.choices.clear()

    assert str(failure(empty)) == "GigaChat вернул пустой ответ"


def test_files_are_not_supported_yet():
    """Фото и документы в запросе — задача 31; пока это честный отказ, а не молчание."""
    photo = FileRef(id="f1", name="solution.jpg", kind=FileKind.IMAGE, media_type="image/jpeg")
    made, client = provider(completion())

    with pytest.raises(LLMError, match="файлы в запросе к GigaChat пока не поддерживаются"):
        chat(made, [LLMMessage(role="user", content="Распознай решение", files=[photo])])

    assert client.payloads == []


def test_closing_the_provider_closes_the_library_client():
    made, client = provider(completion())

    asyncio.run(made.aclose())

    assert client.closed
