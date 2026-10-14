"""Интерфейс исполнения блока: `run(inputs, config, context) -> результат`.

Одинаков для всех трёх способов запуска (python, mcp, http). Результат бывает двух видов:
«готово» и «жду человека». Спецификация — docs/contract.md, раздел «run()»; решение — ADR 0004.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from backend.core.contracts.base import NAME, Strict, explain
from backend.core.contracts.interfaces import LLMClient, PlatformStore, ToolClient
from backend.core.contracts.manifest import Kind, Manifest
from backend.core.contracts.screens import SCREEN_DATA, SCREEN_RESPONSE, ScreenType


class BlockEvent(Strict):
    """Запись для журнала событий запуска."""

    type: str = Field(pattern=NAME)
    data: dict[str, Any] = {}


class Done(Strict):
    """Блок отработал: значения выходов и исход, по которому движок выберет переход."""

    status: Literal["done"] = "done"
    outputs: dict[str, Any] = {}
    outcome: str = "ok"
    events: list[BlockEvent] = []


class Waiting(Strict):
    """Блоку нужен человек: какой экран показать и с какими данными."""

    status: Literal["waiting"] = "waiting"
    screen: ScreenType
    data: dict[str, Any]
    events: list[BlockEvent] = []

    @model_validator(mode="after")
    def _data_fits_screen(self) -> Self:
        SCREEN_DATA[self.screen].model_validate(self.data)
        return self


RunResult = Annotated[Done | Waiting, Field(discriminator="status")]


class RunContext(Strict):
    """Что движок сообщает блоку о запуске. Имён людей здесь нет — только идентификаторы."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    node_id: str
    pipeline_id: str
    params: dict[str, Any] = {}
    student_id: str | None = None
    teacher_id: str | None = None
    # Номер попытки: упавший автоматический блок движок повторяет.
    attempt: int = Field(1, ge=1)
    # Оба поля пусты при первом вызове. При втором: `shown` — данные экрана, которые блок
    # сам попросил показать (ему не нужно вычислять их заново), `human_response` — ответ
    # человека с этого экрана.
    shown: dict[str, Any] | None = None
    human_response: dict[str, Any] | None = None
    # Службы. При вызове блока по сети (mcp, http) не передаются.
    llm: LLMClient | None = Field(None, exclude=True)
    tools: ToolClient | None = Field(None, exclude=True)
    store: PlatformStore | None = Field(None, exclude=True)


class RunRequest(Strict):
    """Тело запроса `POST /run` для блока-сервиса."""

    inputs: dict[str, Any] = {}
    config: dict[str, Any] = {}
    context: RunContext


# Встроенный блок — это асинхронная функция с такой подписью.
BlockRun = Callable[[dict[str, Any], dict[str, Any], RunContext], Awaitable[Done | Waiting]]


def result_problems(manifest: Manifest, result: Done | Waiting) -> list[str]:
    """Чем результат блока расходится с его манифестом; пустой список — всё в порядке."""
    problems = []
    if isinstance(result, Waiting):
        if manifest.kind is Kind.AUTO:
            problems.append("блок `kind: auto` не может ждать человека")
        elif result.screen is not manifest.screen:
            problems.append(
                f"блок просит экран «{result.screen.value}», а в манифесте объявлен "
                f"«{manifest.screen.value}»"
            )
        return problems
    if result.outcome not in manifest.outcomes:
        problems.append(
            f"исход «{result.outcome}» не объявлен в манифесте; "
            f"допустимо: {', '.join(manifest.outcomes)}"
        )
    for name in result.outputs:
        if manifest.output(name) is None:
            problems.append(f"выход «{name}» не объявлен в манифесте")
    return problems


def response_problems(screen: ScreenType, response: dict[str, Any]) -> list[str]:
    """Чем ответ человека не подходит под форму ответа экрана."""
    try:
        SCREEN_RESPONSE[screen].model_validate(response)
    except ValidationError as error:
        return explain(error)
    return []
