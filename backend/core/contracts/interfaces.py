"""Интерфейсы служб, которые блок получает через `context` (ADR 0006).

Здесь только «розетки»: что можно попросить у модели и у MCP-сервера. Настоящие реализации
живут в `backend/llm/` и `backend/mcp_client/`, их подключает слой сборки. Блок о них не
знает, поэтому в тестах вместо модели подставляется фейк с тем же интерфейсом.
"""

from typing import Any, Literal, Protocol, runtime_checkable

from backend.core.contracts.base import Strict
from backend.core.contracts.ports import FileRef


class LLMMessage(Strict):
    role: Literal["system", "user", "assistant"]
    content: str
    files: list[FileRef] = []


class LLMResponse(Strict):
    text: str
    # Разобранный ответ, если модель просили вернуть данные по схеме.
    data: Any = None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Один вызов модели. `schema` — JSON Schema, по которой модель обязана ответить."""
        ...


class ToolInfo(Strict):
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    # False — инструмент с последствиями: агенту он недоступен.
    read_only: bool


@runtime_checkable
class ToolClient(Protocol):
    """MCP-инструменты, разрешённые этому блоку в манифесте (`tools`)."""

    async def list_tools(self) -> list[ToolInfo]: ...

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any: ...
