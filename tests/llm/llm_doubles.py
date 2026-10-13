"""Подделки для тестов слоя ИИ-моделей: подставной провайдер и журнал вызовов «в памяти».

В сеть эти тесты не ходят и ключа не требуют.
"""

from typing import Any

from backend.core.contracts.interfaces import LLMMessage
from backend.llm.providers import ProviderReply


class ScriptedProvider:
    """Провайдер, который отвечает заданным текстом или падает с заданной ошибкой."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, reply: str | Exception = "ответ") -> None:
        self.reply = reply
        self.requests: list[tuple[list[LLMMessage], str | None]] = []

    async def chat(self, messages: list[LLMMessage], *, model: str | None = None) -> ProviderReply:
        self.requests.append((messages, model))
        if isinstance(self.reply, Exception):
            raise self.reply
        return ProviderReply(
            text=self.reply, model=model or self.model, input_tokens=12, output_tokens=5
        )


class MemoryCallLog:
    """Журнал вызовов «в памяти» с тем же методом `record`, что и у журнала в базе."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(self, **fields: Any) -> None:
        self.records.append(fields)
