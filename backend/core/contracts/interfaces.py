"""Интерфейсы служб, которые блок получает через `context` (ADR 0006, ADR 0014).

Здесь только «розетки»: что можно попросить у модели, у MCP-сервера и у хранилища платформы.
Настоящие реализации живут в `backend/llm/`, `backend/mcp_client/` и `backend/models/`, их
подключает слой сборки. Блок о них не знает, поэтому в тестах вместо них подставляются
подделки с тем же интерфейсом.
"""

from typing import Any, Literal, Protocol, runtime_checkable

from backend.core.contracts.base import Strict
from backend.core.contracts.ports import FileRef, Task


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


@runtime_checkable
class PlatformStore(Protocol):
    """Данные платформы, которые может читать встроенный блок (ADR 0014).

    Хранилище уже ограничено преподавателем запуска: блок не называет преподавателя и чужих
    данных не видит. Отдаются только подтверждённые задачи — черновик в урок не попадает.
    """

    async def find_tasks(
        self,
        *,
        topic: str | None = None,
        difficulty: int | None = None,
        subject: str | None = None,
    ) -> list[Task]:
        """Задачи банка по условиям; незаданное не учитывается. Нет таких — пустой список."""
        ...

    async def get_task(self, task_id: str) -> Task | None:
        """Одна задача банка по номеру; `None`, если такой нет."""
        ...
