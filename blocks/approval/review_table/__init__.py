"""Табличное подтверждение списка записей преподавателем."""

from copy import deepcopy
from typing import Any

from backend.core.contracts.run import BlockEvent, Done, RunContext, Waiting
from backend.core.contracts.screens import Column, ReviewTableData, ReviewTableResponse, ScreenType


def _cell(row: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = row
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _key(path: tuple[str, ...]) -> str:
    # Экранирование JSON Pointer отличает вложенное поле от ключа, содержащего точку или /.
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path)


def _table(items: list[dict[str, Any]], editable_fields: str) -> ReviewTableData:
    editable = dict.fromkeys(
        tuple(field.strip().split(".")) for field in editable_fields.split(",") if field.strip()
    )
    paths = dict.fromkeys((name,) for row in items for name in sorted(row))
    paths.update(editable)
    columns = [
        Column(
            key=_key(path),
            title=".".join(path),
            editable=(
                path in editable
                and path[-1] != "id"
                and not path[-1].endswith("_id")
                and any(isinstance(_cell(row, path), str) for row in items)
            ),
        )
        for path in paths
    ]
    rows = [
        {column.key: _cell(row, path) for path, column in zip(paths, columns, strict=True)}
        for row in items
    ]
    # Список пустых записей тоже можно подтвердить или пропустить построчно.
    return ReviewTableData(columns=columns or [Column(key="", title="Запись")], rows=rows)


def validate_run_response(data: dict[str, Any], response: dict[str, Any]) -> str | None:
    table = ReviewTableData.model_validate(data)
    decisions = ReviewTableResponse.model_validate(response).rows
    if sorted(row.index for row in decisions) != list(range(len(table.rows))):
        return "нужно передать одно решение для каждой строки таблицы"
    editable = {column.key for column in table.columns if column.editable}
    for decision in decisions:
        original = table.rows[decision.index]
        for key, value in decision.values.items():
            if (
                not decision.keep
                or key not in editable
                or not isinstance(original.get(key), str)
                or not isinstance(value, str)
                or "\x00" in value
                or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
            ):
                return f"недопустимая правка в строке {decision.index + 1}"
    return None


def _result(items: list[dict[str, Any]], total: int, changed: int) -> Done:
    outcome = "approved" if items else "rejected"
    event = BlockEvent(
        type="approval_decided",
        data={
            "outcome": outcome,
            "kept": len(items),
            "changed": changed,
            "skipped": total - len(items),
        },
    )
    return Done(outputs={"approved": items}, outcome=outcome, events=[event])


async def run(
    inputs: dict[str, Any], config: dict[str, Any], context: RunContext
) -> Done | Waiting:
    items = inputs["items"]
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise ValueError("на подтверждение нужен список записей")
    if not items:
        return _result([], 0, 0)
    if context.human_response is None:
        table = _table(items, config.get("editable_fields", ""))
        return Waiting(screen=ScreenType.REVIEW_TABLE, data=table.model_dump(mode="json"))

    decisions = ReviewTableResponse.model_validate(context.human_response)
    approved = []
    changed = 0
    for decision in sorted(decisions.rows, key=lambda row: row.index):
        if not decision.keep:
            continue
        row = deepcopy(items[decision.index])
        for key, value in decision.values.items():
            path = [part.replace("~1", "/").replace("~0", "~") for part in key[1:].split("/")]
            target = row
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
        changed += row != items[decision.index]
        approved.append(row)
    return _result(approved, len(items), changed)
