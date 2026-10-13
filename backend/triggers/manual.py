"""Триггер «вручную»: преподаватель нажал «Запустить» (ADR 0013).

Перед стартом пайплайн проверяется заново — блоки могли обновиться после сохранения
(ADR 0011), — и сверяются значения параметров. Отказ — это `LaunchRefused` со списком
причин; запуск при этом не создаётся.
"""

import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.core.contracts.pipeline import BlockNode, Param, ParamType, Pipeline
from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.state import RunState
from backend.core.contracts.wiring import Problem
from backend.core.validator import validate
from backend.triggers.assembly import Assembly

_TYPE_NAMES = {
    ParamType.STRING: "строка",
    ParamType.INTEGER: "целое число",
    ParamType.NUMBER: "число",
    ParamType.BOOLEAN: "да или нет (true/false)",
}


class PipelineNotFound(Exception):
    """Такого пайплайна у этого преподавателя нет."""


class LaunchRefused(Exception):
    """Запуск не начат. `problems` — причины: узел (если он есть), код и текст."""

    def __init__(self, message: str, problems: list[Problem]) -> None:
        super().__init__(message)
        self.problems = problems


async def start_manual(
    assembly: Assembly,
    *,
    teacher_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    params: Mapping[str, Any] | None = None,
) -> RunState:
    """Запускает последнюю версию пайплайна преподавателя и выполняет её, пока она идёт сама.

    Возвращает состояние запуска: он закончился, встал на паузу или остановился с ошибкой.
    """
    row = await assembly.pipelines.get(teacher_id, pipeline_id)
    pipeline = None if row is None else await assembly.pipelines.load(row.id, row.latest_version)
    if row is None or pipeline is None:
        raise PipelineNotFound("пайплайн не найден")
    # Незаполненное значение — то же, что его отсутствие: тогда берётся значение по умолчанию.
    given = {name: value for name, value in (params or {}).items() if value is not None}
    problems = launch_problems(assembly, pipeline, TriggerType.MANUAL, given)
    if problems:
        raise LaunchRefused("пайплайн нельзя запустить", problems)
    return await assembly.engine().start(
        pipeline,
        run_id=str(uuid.uuid4()),
        pipeline_id=str(row.id),
        pipeline_version=row.latest_version,
        event=Event(trigger=TriggerType.MANUAL, occurred_at=datetime.now(UTC)),
        params=given,
        teacher_id=str(teacher_id),
    )


def launch_problems(
    assembly: Assembly, pipeline: Pipeline, trigger: TriggerType, params: Mapping[str, Any]
) -> list[Problem]:
    """Что мешает запустить пайплайн этим способом; пустой список — можно запускать."""
    start = pipeline.trigger()
    if all(launch.type is not trigger for launch in start.launches):
        allowed = ", ".join(launch.type.value for launch in start.launches)
        return [
            Problem(
                start.id,
                "launch_not_allowed",
                f"у пайплайна нет способа запуска «{trigger.value}»; есть только: {allowed}",
            )
        ]
    errors = validate(pipeline, assembly.registry.manifests).errors
    if errors:
        return errors
    # Блок `mcp` или `http` валидатору известен, но вызвать его пока может быть нечем.
    not_callable = [
        Problem(node.id, "block_not_callable", f"блок «{node.block}» пока нечем вызвать")
        for node, _ in pipeline.walk()
        if isinstance(node, BlockNode) and node.block not in assembly.registry.blocks
    ]
    return not_callable or [
        Problem(start.id, "bad_param", text) for text in param_problems(pipeline, params)
    ]


def param_problems(pipeline: Pipeline, given: Mapping[str, Any]) -> list[str]:
    """Чем значения параметров не подходят пайплайну; пустой список — всё в порядке."""
    known = {param.name for param in pipeline.params}
    problems = [f"у пайплайна нет параметра «{name}»" for name in sorted(set(given) - known)]
    for param in pipeline.params:
        value = given.get(param.name, param.default)
        if value is None:
            problems.append(f"параметр «{param.name}» ({param.title}) не заполнен")
        elif not _fits(param, value):
            problems.append(
                f"параметр «{param.name}» ({param.title}): ожидается "
                f"{_TYPE_NAMES[param.type]}, а получено {value!r}"
            )
    return problems


def _fits(param: Param, value: Any) -> bool:
    """Подходит ли значение под тип параметра — по тому же правилу, что и значение по умолчанию."""
    # «Не число» и бесконечность база не хранит: в состоянии запуска они стали бы пустым
    # значением (ADR 0007), и блок получил бы «ничего» вместо числа.
    if isinstance(value, float) and not math.isfinite(value):
        return False
    try:
        Param(name=param.name, title=param.title, type=param.type, default=value)
    except ValidationError:
        return False
    return True
