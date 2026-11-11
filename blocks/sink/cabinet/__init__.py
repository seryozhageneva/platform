"""Блок «Получатель: кабинет» записывает результат для преподавателя или его ученика (ADR 0027)."""

import hashlib
import json
from typing import Any

from backend.core.contracts.run import BlockEvent, Done, RunContext


def _recipient(to: str, inputs: dict[str, Any], context: RunContext) -> str | None:
    if to == "teacher":
        return None
    if to == "student":
        if context.student_id is None:
            raise ValueError("у запуска нет ученика: выберите кабинет преподавателя")
        return context.student_id
    value = inputs.get("recipient")
    student_id = value.get("student_id") if isinstance(value, dict) else None
    if not isinstance(student_id, str) or not student_id:
        raise ValueError("на входе «Кому адресовано» не указан ученик")
    return student_id


def result_key(*parts: Any) -> str:
    """Устойчивый ключ записи: одинаковые входы дают один ключ, и повтор не создаёт дубля."""
    text = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    title = config.get("title") or "Результат"
    student_id = _recipient(config.get("to", "teacher"), inputs, context)
    content = inputs["content"]
    result_id = await store.publish_result(
        key=result_key(title, student_id, content),
        title=title,
        content=content,
        student_id=student_id,
    )
    return Done(
        events=[
            BlockEvent(
                type="result_published",
                data={"result_id": result_id, "to": "teacher" if student_id is None else "student"},
            )
        ]
    )
