"""Провайдер GigaChat на официальной библиотеке `gigachat` (ADR 0012).

Библиотека сама получает временный токен доступа по ключу и обновляет его каждые полчаса.
Серверы GigaChat подписаны российским корневым сертификатом: его файл передаётся библиотеке,
а проверка сертификатов не отключается никогда.
"""

import ssl
from pathlib import Path
from typing import Any

import httpx
from gigachat import GigaChat
from gigachat.exceptions import (
    AuthenticationError,
    ForbiddenError,
    GigaChatException,
    RateLimitError,
    ResponseError,
)
from gigachat.models import Chat, Messages

from backend.core.contracts.interfaces import LLMMessage
from backend.llm.providers import LLMError, ProviderReply

TIMEOUT_SECONDS = 60.0


class GigaChatProvider:
    name = "gigachat"

    def __init__(
        self,
        *,
        auth_key: str,
        scope: str,
        model: str,
        ca_bundle_file: Path,
        client: Any = None,
    ) -> None:
        self.model = model
        # `client` подставляют тесты; в работе клиент создаётся здесь.
        self._client = client or GigaChat(
            credentials=auth_key,
            scope=scope,
            model=model,
            verify_ssl_certs=True,
            ca_bundle_file=str(ca_bundle_file),
            timeout=TIMEOUT_SECONDS,
            # Повторы делает движок (ADR 0010); вместе с повторами библиотеки вышло бы 3 × 3.
            max_retries=0,
        )

    async def chat(self, messages: list[LLMMessage], *, model: str | None = None) -> ProviderReply:
        if any(message.files for message in messages):
            raise LLMError(
                "unsupported", "файлы в запросе к GigaChat пока не поддерживаются (задача 31)"
            )
        payload = Chat(
            model=model or self.model,
            messages=[Messages(role=message.role, content=message.content) for message in messages],
        )
        try:
            completion = await self._client.achat(payload)
        # `from None`: в тексте ошибки библиотеки есть адрес и заголовки ответа сервера.
        except (AuthenticationError, ForbiddenError):
            raise LLMError(
                "auth",
                "GigaChat не принял ключ: проверь GIGACHAT_AUTH_KEY и GIGACHAT_SCOPE в файле .env",
            ) from None
        except RateLimitError:
            raise LLMError(
                "rate_limit", "GigaChat ответил, что запросов слишком много или лимит исчерпан"
            ) from None
        except ResponseError as error:
            raise LLMError("provider", f"GigaChat ответил ошибкой {error.status_code}") from None
        except ssl.SSLError:
            raise LLMError(
                "certificate",
                "файл из GIGACHAT_CA_BUNDLE_FILE не читается как сертификат: нужен текстовый "
                "файл, который начинается со строки -----BEGIN CERTIFICATE-----",
            ) from None
        except httpx.TimeoutException:
            raise LLMError(
                "timeout", f"GigaChat не ответил за {TIMEOUT_SECONDS:.0f} секунд"
            ) from None
        except httpx.ConnectError as error:
            if "CERTIFICATE_VERIFY_FAILED" in str(error):
                raise LLMError(
                    "certificate",
                    "не удалось проверить сертификат GigaChat: проверь файл из "
                    "GIGACHAT_CA_BUNDLE_FILE в .env",
                ) from None
            raise LLMError("network", "нет связи с GigaChat: проверь интернет") from None
        except (httpx.HTTPError, GigaChatException) as error:
            raise LLMError(
                "network", f"запрос к GigaChat не прошёл ({type(error).__name__})"
            ) from None
        if not completion.choices:
            raise LLMError("provider", "GigaChat вернул пустой ответ")
        return ProviderReply(
            text=completion.choices[0].message.content,
            model=completion.model,
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
