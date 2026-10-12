"""Формат пайплайна: JSON-описание графа из узлов, переходов и привязок входов.

Связей два вида. Переход отвечает на вопрос «что выполнять дальше» и выбирается по исходу
узла. Привязка входа отвечает на вопрос «откуда взять данные»: вход читает последнее
значение указанного выхода. Спецификация — docs/contract.md, раздел «Пайплайн»; ADR 0005.
"""

import json
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import Field, ValidationError, model_validator

from backend.core.contracts.base import NAME, ContractError, Strict, explain
from backend.core.contracts.ports import TriggerType

# Ссылка на выход: «узел.порт» или «узел.порт.поле» (поле — у записи из «для каждого»).
REF = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$"
Ref = Annotated[str, Field(pattern=REF)]
# Привязка — одна ссылка или несколько на выбор: берётся значение, записанное последним.
# Несколько ссылок нужны там, где ветки графа сходятся: ответ пришёл либо из формы,
# либо после распознавания фото.
Binding = Ref | Annotated[list[Ref], Field(min_length=1)]
NodeId = Annotated[str, Field(pattern=NAME)]


class ParamRef(Strict):
    """Ссылка на параметр пайплайна: `{"$param": "topic"}`."""

    param: str = Field(alias="$param", pattern=NAME)


class ParamType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


class Param(Strict):
    """Значение, которое преподаватель заполняет при назначении, а не зашивает в схему."""

    name: str = Field(pattern=NAME)
    title: str
    type: ParamType
    default: Any = None

    @model_validator(mode="after")
    def _default_fits_type(self) -> Self:
        fits = {
            ParamType.STRING: lambda v: isinstance(v, str),
            ParamType.BOOLEAN: lambda v: isinstance(v, bool),
            ParamType.INTEGER: lambda v: isinstance(v, int) and not isinstance(v, bool),
            ParamType.NUMBER: lambda v: isinstance(v, int | float) and not isinstance(v, bool),
        }
        if self.default is not None and not fits[self.type](self.default):
            raise ValueError(
                f"значение по умолчанию {self.default!r} не подходит под тип {self.type.value}"
            )
        return self


class Launch(Strict):
    """Один способ запуска пайплайна."""

    type: TriggerType
    cron: str | None = None
    settings: dict[str, Any] = {}

    @model_validator(mode="after")
    def _cron_only_for_schedule(self) -> Self:
        if (self.type is TriggerType.SCHEDULE) != (self.cron is not None):
            raise ValueError("поле `cron` нужно способу запуска `schedule` и только ему")
        return self


class Limit(Strict):
    """Ограничитель: сколько раз узел можно пройти и куда идти, когда попытки кончились."""

    max: Annotated[int, Field(ge=1)] | ParamRef
    # Не задано — ветка на этом заканчивается.
    otherwise: NodeId | None = None
    # Счётчик обнуляется при каждом выполнении этого узла. Не задано — один на весь запуск.
    reset_on: NodeId | None = None


class Transition(Strict):
    """Переход «после узла `from` при исходе `when` выполнить узел `to`».

    Переход без `when` срабатывает при любом исходе, для которого нет своего перехода.
    """

    source: NodeId = Field(alias="from")
    when: str | None = Field(None, pattern=NAME)
    target: NodeId = Field(alias="to")


class TriggerNode(Strict):
    """Стартовый узел. У него один выход — `event` типа Event."""

    id: NodeId
    type: Literal["trigger"]
    title: str = ""
    launches: list[Launch] = Field(min_length=1)


class _Step(Strict):
    id: NodeId
    title: str = ""
    limit: Limit | None = None


class BlockNode(_Step):
    """Блок со своими настройками и привязками входов: имя входа -> откуда взять данные."""

    type: Literal["block"]
    block: str
    config: dict[str, Any] = {}
    inputs: dict[str, Binding] = {}


class SwitchNode(_Step):
    """Развилка по значению: исход узла — значение поля `field` у данных `value`."""

    type: Literal["switch"]
    value: Ref
    field: str = Field(pattern=NAME)


class ForEachNode(_Step):
    """«Для каждого»: выполнить `body` отдельно для каждого элемента списка `over`.

    Внутри тела текущий элемент доступен как выход `item` этого узла. `collect` говорит,
    что собрать в выход `results`: одно значение или запись из нескольких (тогда `as` —
    название записи, по которому её поля потом читаются как «узел.порт.поле»).
    """

    type: Literal["for_each"]
    over: Ref
    body: "Body"
    collect: Ref | dict[Annotated[str, Field(pattern=NAME)], Binding] | None = None
    record: str | None = Field(None, alias="as", pattern=NAME)

    @model_validator(mode="after")
    def _record_goes_with_fields(self) -> Self:
        if isinstance(self.collect, dict) != (self.record is not None):
            raise ValueError("`as` (название записи) нужно тогда, когда `collect` — набор полей")
        return self


Step = Annotated[BlockNode | SwitchNode | ForEachNode, Field(discriminator="type")]
Node = Annotated[TriggerNode | BlockNode | SwitchNode | ForEachNode, Field(discriminator="type")]


class Body(Strict):
    """Тело «для каждого»: маленький граф, который начинается с узла `start`."""

    start: NodeId
    nodes: list[Step] = Field(min_length=1)
    transitions: list[Transition] = []


ForEachNode.model_rebuild()


def param_refs(value: Any) -> Iterator[str]:
    """Имена параметров, на которые ссылается значение настройки (на любой глубине)."""
    if isinstance(value, ParamRef):
        yield value.param
    elif isinstance(value, dict):
        if set(value) == {"$param"}:
            if not isinstance(value["$param"], str):
                raise ValueError(
                    f'ссылка на параметр пишется как {{"$param": "имя"}}, '
                    f"а здесь {value['$param']!r}"
                )
            yield value["$param"]
        else:
            for item in value.values():
                yield from param_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from param_refs(item)


class Pipeline(Strict):
    format: Literal[1] = 1
    id: str = Field(pattern=NAME)
    name: str
    description: str = ""
    params: list[Param] = []
    nodes: list[Node] = Field(min_length=1)
    transitions: list[Transition] = []

    def walk(self) -> Iterator[tuple[Any, tuple[str, ...]]]:
        """Все узлы на всех уровнях вместе с путём — списком «для каждого», в которые вложен."""

        def visit(nodes: list[Any], path: tuple[str, ...]) -> Iterator[Any]:
            for node in nodes:
                yield node, path
                if isinstance(node, ForEachNode):
                    yield from visit(node.body.nodes, (*path, node.id))

        yield from visit(self.nodes, ())

    def trigger(self) -> TriggerNode:
        return next(node for node in self.nodes if isinstance(node, TriggerNode))

    @model_validator(mode="after")
    def _is_consistent(self) -> Self:
        paths = {node.id: path for node, path in self.walk()}
        ids = [node.id for node, _ in self.walk()]
        repeated = sorted({name for name in ids if ids.count(name) > 1})
        if repeated:
            raise ValueError(f"имя узла повторяется: {', '.join(repeated)}")

        triggers = [node for node in self.nodes if isinstance(node, TriggerNode)]
        if len(triggers) != 1:
            raise ValueError(
                f"в пайплайне должен быть ровно один узел-триггер, а их {len(triggers)}"
            )

        params = {param.name: param for param in self.params}
        if len(params) != len(self.params):
            raise ValueError("имя параметра повторяется")

        self._check_level(self.nodes, self.transitions, where="пайплайн")
        records = []
        for node, _ in self.walk():
            if isinstance(node, ForEachNode):
                if node.body.start not in {inner.id for inner in node.body.nodes}:
                    raise ValueError(
                        f"узел «{node.id}»: тело начинается с узла «{node.body.start}», "
                        "которого в теле нет"
                    )
                self._check_level(node.body.nodes, node.body.transitions, f"тело «{node.id}»")
                if node.record:
                    records.append(node.record)
            if isinstance(node, BlockNode):
                for name in param_refs(node.config):
                    if name not in params:
                        raise ValueError(
                            f"узел «{node.id}»: в настройках ссылка на параметр «{name}», "
                            "которого нет в `params`"
                        )
            limit = getattr(node, "limit", None)
            if limit is not None:
                if limit.reset_on and limit.reset_on not in ids:
                    raise ValueError(
                        f"узел «{node.id}»: ограничитель обнуляется на узле "
                        f"«{limit.reset_on}», которого нет"
                    )
                outer = paths.get(limit.reset_on, ())
                if limit.reset_on and outer != paths[node.id][: len(outer)]:
                    raise ValueError(
                        f"узел «{node.id}»: ограничитель обнуляется на узле "
                        f"«{limit.reset_on}», а он внутри «для каждого» и отсюда не виден"
                    )
                if isinstance(limit.max, ParamRef):
                    param = params.get(limit.max.param)
                    if param is None or param.type is not ParamType.INTEGER:
                        raise ValueError(
                            f"узел «{node.id}»: ограничитель ссылается на параметр "
                            f"«{limit.max.param}» — нужен параметр типа integer"
                        )
        if len(set(records)) != len(records):
            raise ValueError("название записи (`as`) повторяется у двух узлов «для каждого»")
        return self

    @staticmethod
    def _check_level(nodes: list[Any], transitions: list[Transition], where: str) -> None:
        """Переходы и ограничители одного уровня графа ведут к узлам этого же уровня."""
        level = {node.id: node for node in nodes}
        seen = set()
        for move in transitions:
            for end in (move.source, move.target):
                if end not in level:
                    raise ValueError(
                        f"{where}: переход «{move.source} → {move.target}» ведёт к узлу "
                        f"«{end}», которого на этом уровне нет"
                    )
            if isinstance(level[move.target], TriggerNode):
                raise ValueError(f"{where}: переход не может вести в узел-триггер")
            if isinstance(level[move.source], TriggerNode) and move.when is not None:
                raise ValueError(f"{where}: у триггера нет исходов, переход из него — без `when`")
            if (move.source, move.when) in seen:
                raise ValueError(
                    f"{where}: из узла «{move.source}» два перехода с одним условием "
                    f"({move.when or 'любой исход'})"
                )
            seen.add((move.source, move.when))
        for node in nodes:
            limit = getattr(node, "limit", None)
            if limit is not None and limit.otherwise and limit.otherwise not in level:
                raise ValueError(
                    f"{where}: ограничитель узла «{node.id}» ведёт к узлу "
                    f"«{limit.otherwise}», которого на этом уровне нет"
                )


def parse_pipeline(source: str | dict[str, Any], what: str = "пайплайн") -> Pipeline:
    """Разбирает пайплайн из текста JSON или готового словаря."""
    try:
        data = json.loads(source) if isinstance(source, str) else source
    except json.JSONDecodeError as error:
        raise ContractError(what, [f"это не JSON: {error}"]) from error
    try:
        return Pipeline.model_validate(data)
    except ValidationError as error:
        raise ContractError(what, explain(error)) from error


def load_pipeline(path: Path) -> Pipeline:
    return parse_pipeline(path.read_text(encoding="utf-8"), what=f"пайплайн {path.name}")
