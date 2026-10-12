"""Манифест блока (`block.yaml`): всё, что ядро и редактор знают о блоке.

Спецификация — docs/contract.md, раздел «Манифест»; решение — ADR 0004.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from backend.core.contracts.base import NAME, ContractError, Strict, explain
from backend.core.contracts.ports import InputPort, OutputPort, check_json_schema
from backend.core.contracts.screens import ScreenType


class Category(StrEnum):
    """Семь категорий блоков. Триггер — узел ядра, манифеста у него нет."""

    SOURCE = "source"
    TRANSFORM = "transform"
    STUDENT = "student"
    CHECK = "check"
    AI_PROCESS = "ai_process"
    APPROVAL = "approval"
    SINK = "sink"


class Kind(StrEnum):
    AUTO = "auto"
    INTERACTIVE = "interactive"
    APPROVAL = "approval"


# Какие экраны кому показываются: ученику или преподавателю.
SCREENS_BY_KIND: dict[Kind, set[ScreenType]] = {
    Kind.AUTO: set(),
    Kind.INTERACTIVE: {ScreenType.ANSWER_FORM, ScreenType.CONFIRM_RECOGNIZED},
    Kind.APPROVAL: {ScreenType.REVIEW_TABLE, ScreenType.REVIEW_DOCUMENT},
}


class PythonRuntime(Strict):
    """Встроенный блок: функция `run` в пакете Python, записанная как «модуль:функция»."""

    type: Literal["python"]
    entrypoint: str = Field(pattern=r"^[a-z_][a-z0-9_.]*:[a-z_][a-z0-9_]*$")


class McpRuntime(Strict):
    """Блок-обёртка над одним инструментом MCP-сервера."""

    type: Literal["mcp"]
    server: str = Field(pattern=NAME)
    tool: str = Field(pattern=NAME)


class HttpRuntime(Strict):
    """Отдельный сервис: `GET {url}/manifest`, `POST {url}/run`."""

    type: Literal["http"]
    url: str = Field(pattern=r"^https?://")


Runtime = Annotated[PythonRuntime | McpRuntime | HttpRuntime, Field(discriminator="type")]


class ToolRef(Strict):
    """MCP-инструмент, который разрешено вызывать агенту внутри блока. Только чтение."""

    server: str = Field(pattern=NAME)
    tool: str = Field(pattern=NAME)


def _empty_config() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


class Manifest(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    name: str
    description: str
    author: str
    category: Category
    kind: Kind = Kind.AUTO
    screen: ScreenType | None = None
    inputs: list[InputPort] = []
    outputs: list[OutputPort] = []
    # JSON Schema настроек: из неё редактор строит форму.
    config: dict[str, Any] = Field(default_factory=_empty_config)
    outcomes: list[Annotated[str, Field(pattern=NAME)]] = Field(["ok"], min_length=1)
    runtime: Runtime
    tools: list[ToolRef] = []
    side_effects: bool = False

    @field_validator("config")
    @classmethod
    def _config_is_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("настройки описываются как JSON Schema с `type: object`")
        check_json_schema(value)
        return value

    @model_validator(mode="after")
    def _is_consistent(self) -> Self:
        for title, names in (
            ("входа", [port.name for port in self.inputs]),
            ("выхода", [port.name for port in self.outputs]),
            ("исхода", self.outcomes),
        ):
            repeated = sorted({name for name in names if names.count(name) > 1})
            if repeated:
                raise ValueError(f"имя {title} повторяется: {', '.join(repeated)}")

        if self.kind is Kind.AUTO and self.screen is not None:
            raise ValueError("блок `kind: auto` человека не ждёт, поле `screen` ему не нужно")
        if self.kind is not Kind.AUTO:
            allowed = sorted(screen.value for screen in SCREENS_BY_KIND[self.kind])
            if self.screen is None:
                raise ValueError(
                    f"блок `kind: {self.kind.value}` ждёт человека: укажи `screen` "
                    f"({', '.join(allowed)})"
                )
            if self.screen.value not in allowed:
                raise ValueError(
                    f"экран `{self.screen.value}` не подходит для `kind: {self.kind.value}`; "
                    f"допустимо: {', '.join(allowed)}"
                )

        inputs = {port.name for port in self.inputs}
        settings = self.config.get("properties", {})
        for port in self.outputs:
            if port.same_as and port.same_as not in inputs:
                raise ValueError(
                    f"выход «{port.name}»: `same_as` ссылается на вход "
                    f"«{port.same_as}», которого нет"
                )
            if port.from_config and port.from_config not in settings:
                raise ValueError(
                    f"выход «{port.name}»: `from_config` ссылается на настройку "
                    f"«{port.from_config}», которой нет в `config`"
                )
        return self

    def input(self, name: str) -> InputPort | None:
        return next((port for port in self.inputs if port.name == name), None)

    def output(self, name: str) -> OutputPort | None:
        return next((port for port in self.outputs if port.name == name), None)


def parse_manifest(source: str | dict[str, Any], what: str = "манифест") -> Manifest:
    """Разбирает манифест из текста YAML или готового словаря."""
    try:
        data = yaml.safe_load(source) if isinstance(source, str) else source
    except yaml.YAMLError as error:
        raise ContractError(what, [f"это не YAML: {error}"]) from error
    if not isinstance(data, dict):
        raise ContractError(what, ["ожидался набор полей «название: значение»"])
    try:
        return Manifest.model_validate(data)
    except ValidationError as error:
        raise ContractError(what, explain(error)) from error


def load_manifest(path: Path) -> Manifest:
    return parse_manifest(path.read_text(encoding="utf-8"), what=f"манифест {path.name}")
