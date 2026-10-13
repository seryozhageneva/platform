"""Откуда узел берёт данные: чтение значений из состояния запуска по ссылкам.

Привязка входа, развилка, «для каждого» и его `collect` читают одно и то же — последнее
значение выхода `узел.порт`, иногда поле записи `узел.порт.поле`. Здесь это собрано в одном
месте, отдельно от движка, который решает, какой узел выполнять следующим (ADR 0010).
"""

import copy
from collections.abc import Collection, Mapping
from typing import Any

from backend.core.contracts.pipeline import Binding, ForEachNode
from backend.core.contracts.state import RunState

# «Данных нет» — не то же, что пустое значение: записать на выход `null` блок вправе.
MISSING: Any = object()


def read_ref(state: RunState, ref: str) -> Any:
    """Значение по ссылке «узел.порт» или «узел.порт.поле»; `MISSING` — если его нет.

    Возвращается копия: правка на месте не меняет выход в состоянии.
    """
    node_id, port, *field = ref.split(".")
    written = state.ports.get(node_id, {})
    if port not in written:
        return MISSING
    value = written[port]
    if field:
        if not isinstance(value, dict) or field[0] not in value:
            return MISSING
        value = value[field[0]]
    return copy.deepcopy(value)


def read_binding(state: RunState, bound: Binding) -> Any:
    """Значение привязки. Из нескольких ссылок на выбор берётся записанная последней."""
    refs = bound if isinstance(bound, list) else [bound]
    latest = state.latest(refs)
    return MISSING if latest is None else read_ref(state, latest)


def with_params(value: Any, params: Mapping[str, Any]) -> Any:
    """Настройки узла, в которых ссылки `{"$param": "имя"}` заменены значениями."""
    if isinstance(value, dict):
        if set(value) == {"$param"}:
            return params[value["$param"]]
        return {key: with_params(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [with_params(item, params) for item in value]
    return value


def body_ids(node: ForEachNode) -> list[str]:
    """Все узлы тела «для каждого», включая тела вложенных «для каждого»."""
    ids = []
    for inner in node.body.nodes:
        ids.append(inner.id)
        if isinstance(inner, ForEachNode):
            ids += body_ids(inner)
    return ids


def forget(state: RunState, node_ids: Collection[str]) -> None:
    """Убирает из состояния всё, что оставили узлы: выходы, счётчики, номер элемента.

    Так тело «для каждого» очищается перед очередным элементом: иначе он получил бы
    значения и потраченные попытки прошлого. Порядок записи правится здесь же (ADR 0009).
    """
    for node_id in node_ids:
        state.ports.pop(node_id, None)
        state.counters.pop(node_id, None)
        state.item_index.pop(node_id, None)
    state.write_order = [ref for ref in state.write_order if ref.split(".")[0] not in node_ids]


def forget_output(state: RunState, node_id: str, port: str) -> None:
    """Убирает один выход узла — например, `item`, когда «для каждого» прошёл весь список."""
    written = state.ports.get(node_id, {})
    written.pop(port, None)
    if not written:
        state.ports.pop(node_id, None)
    state.write_order = [ref for ref in state.write_order if ref != f"{node_id}.{port}"]
