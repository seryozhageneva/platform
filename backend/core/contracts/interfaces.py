"""Интерфейсы служб, которые блок получает через `context` (ADR 0006, ADR 0014).

Здесь только «розетки»: что можно попросить у модели, у MCP-сервера и у хранилища платформы.
Настоящие реализации живут в `backend/llm/`, `backend/mcp_client/` и `backend/models/`, их
подключает слой сборки. Блок о них не знает, поэтому в тестах вместо них подставляются
подделки с тем же интерфейсом.
"""

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, JsonValue

from backend.core.contracts.base import Strict
from backend.core.contracts.ports import FileKind, FileRef, Task


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


class WorkResult(Strict):
    """Итог одной работы ученика — без текста ответа и комментария (ADR 0031).

    `topic` — тема задачи из банка; у работы из Moodle или по задаче не из банка тема пуста.
    `status`: `unchecked` — работу ещё не проверили, `preliminary` — оценил ИИ и преподаватель
    её ещё не подтвердил, `confirmed` — оценка окончательная. У непроверенной работы
    `correct`, `score` и `max_score` пусты.
    """

    task_id: str | None = None
    topic: str | None = None
    source: Literal["platform", "moodle"]
    submitted_at: datetime
    status: Literal["unchecked", "preliminary", "confirmed"]
    correct: bool | None = None
    score: float | None = None
    max_score: float | None = None


class StudentResults(Strict):
    """Как учился один ученик преподавателя за период (ADR 0031).

    `works` — работы от старых к новым; `hints` — сколько подсказок тьютора ученик получил.
    Ученик без работ за период тоже есть в списке: это тоже результат.
    """

    student_id: str
    name: str
    works: list[WorkResult] = []
    hints: int = Field(0, ge=0)


@runtime_checkable
class PlatformStore(Protocol):
    """Данные платформы для встроенного блока (ADR 0014, ADR 0023, ADR 0026).

    Хранилище уже ограничено преподавателем запуска: блок не называет преподавателя и чужих
    данных не видит. Отдаются только подтверждённые задачи — черновик в урок не попадает.
    Операции записи привязаны к запуску и узлу. Блок передаёт устойчивый ключ результата:
    при повторе того же ключа и операции хранилище возвращает уже сохранённую запись.
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

    async def get_file(self, file_id: str) -> FileRef | None:
        """Описание загруженного файла по номеру; `None`, если такого нет (ADR 0023)."""
        ...

    async def read_file(self, file_id: str) -> bytes | None:
        """Содержимое загруженного файла по номеру; `None`, если такого нет (ADR 0023)."""
        ...

    async def find_results(self, *, since: datetime) -> list[StudentResults]:
        """Результаты всех учеников преподавателя с момента `since`, по алфавиту (ADR 0031).

        `since` — время с часовым поясом; без пояса — ValueError.

        Пробные запуски преподавателя без ученика сюда не попадают.
        """
        ...

    async def save_task(self, task: Task, *, key: str) -> Task:
        """Сохранить подтверждённую задачу и вернуть её с номером в банке."""
        ...

    async def save_file(
        self, *, key: str, name: str, kind: FileKind, media_type: str, content: bytes
    ) -> FileRef:
        """Сохранить готовый файл преподавателя и вернуть ссылку на него."""
        ...

    async def publish_result(
        self, *, key: str, title: str, content: JsonValue, student_id: str | None = None
    ) -> str:
        """Записать результат для преподавателя или его ученика и вернуть номер записи.

        Чужой или неизвестный ученик вызывает ValueError. Без ученика результат адресован
        преподавателю. Содержимое для ученика блок формирует из предназначенных ему данных.
        """
        ...
