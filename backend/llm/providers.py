"""Провайдер модели — тот, кто на самом деле отвечает: GigaChat или заглушка (ADR 0012).

Провайдер умеет одно: получить сообщения и вернуть текст с числом токенов. Всё общее —
ответ по схеме, замер времени, журнал вызовов — делает слой в `client.py`, поэтому новый
провайдер добавляется одним небольшим файлом.
"""

from dataclasses import dataclass
from typing import Protocol

from backend.core.contracts.interfaces import LLMMessage


class LLMError(RuntimeError):
    """Вызов модели не удался. Текст понятен человеку, ключа и адресов в нём нет.

    `kind` — короткое обозначение причины; оно попадает в журнал вызовов вместо текста,
    чтобы в журнале не оказалось ни слова из запроса или ответа.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ProviderReply:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class Provider(Protocol):
    # Имя провайдера и модель, которой он отвечает, если блок не попросил другую.
    name: str
    model: str

    async def chat(self, messages: list[LLMMessage], *, model: str | None = None) -> ProviderReply:
        """Один запрос к модели. Любую неудачу провайдер превращает в `LLMError`."""
        ...


class StubProvider:
    """Заглушка для режима `LLM_PROVIDER=fake`: отвечает одной фразой, в сеть не ходит.

    Нужна, чтобы платформа запускалась без ключа. Ответить по схеме заглушка не умеет:
    в тестах блоков для этого есть `FakeLLM` из `backend/core/contracts/testing.py`.
    """

    name = "fake"
    model = "fake"

    def __init__(self, text: str = "Это ответ заглушки: настоящая модель не подключена.") -> None:
        self._text = text

    async def chat(self, messages: list[LLMMessage], *, model: str | None = None) -> ProviderReply:
        return ProviderReply(
            text=self._text,
            model=model or self.model,
            input_tokens=sum(len(message.content.split()) for message in messages),
            output_tokens=len(self._text.split()),
        )
