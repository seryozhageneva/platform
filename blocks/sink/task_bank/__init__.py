"""Блок «Получатель: банк задач» сохраняет подтверждённую задачу в банк (ADR 0027).

Подтверждает задачу узел подтверждения перед этим блоком, поэтому в банк она попадает сразу
подтверждённой (ADR 0026).
"""

import hashlib
import json
from typing import Any

from backend.core.contracts.ports import Task
from backend.core.contracts.run import BlockEvent, Done, RunContext


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    task = Task.model_validate(inputs["task"])
    # Ключ — из самой задачи: повтор узла с той же задачей возвращает уже сохранённую.
    text = json.dumps(task.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    saved = await store.save_task(task, key=hashlib.sha256(text.encode()).hexdigest())
    return Done(
        outputs={"task": saved.model_dump(mode="json")},
        events=[BlockEvent(type="task_saved", data={"task_id": saved.id})],
    )
