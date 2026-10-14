"""Блок «Источник: банк задач»: берёт задачу для урока (ADR 0015).

Задачи блок читает через хранилище платформы в `context.store` (ADR 0014). Хранилище уже
ограничено преподавателем запуска и отдаёт только подтверждённые задачи, поэтому блок решает
одно: какую из подходящих задач дать ученику.

Подстройка сложности: если поданы прошлая задача и вердикт по ней, после верного ответа
берётся сложность на единицу выше, после неверного — на единицу ниже, но не ниже 1. Если на
этой сложности задач нет, остаётся сложность прошлой задачи. Прошлая задача подряд не
повторяется, если есть другие.
"""

import random
from typing import Any

from backend.core.contracts.interfaces import PlatformStore
from backend.core.contracts.ports import Task, Verdict
from backend.core.contracts.run import BlockEvent, Done, RunContext


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы: его кладёт в context слой сборки")
    task_id = config.get("task_id")
    if task_id:
        return await _by_id(store, task_id)

    previous = Task.model_validate(inputs["previous"]) if "previous" in inputs else None
    verdict = Verdict.model_validate(inputs["verdict"]) if "verdict" in inputs else None
    start = config.get("difficulty", 1)
    levels = [start]
    if config.get("adapt", True) and previous is not None and _is_about(verdict, previous):
        step = 1 if verdict.correct else -1
        levels = list(dict.fromkeys([max(1, previous.difficulty + step), previous.difficulty]))

    conditions = {"topic": config.get("topic"), "subject": config.get("subject")}
    for level in levels:
        found = await store.find_tasks(difficulty=level, **conditions)
        if found:
            break
    else:
        missing = BlockEvent(type="no_tasks", data={**conditions, "difficulty": levels[0]})
        return Done(outcome="empty", events=[missing])

    others = [task for task in found if previous is None or task.id != previous.id]
    # Выбор случайный, но повторный вызов в том же запуске с той же прошлой задачей даёт
    # ту же задачу: упавший блок движок повторяет, и выбор при этом не должен меняться.
    chooser = random.Random(f"{context.run_id}:{previous.id if previous else ''}")
    task = chooser.choice(others or found)
    return _chosen(task, _reason(task, previous))


def _is_about(verdict: Verdict | None, previous: Task) -> bool:
    """Вердикт относится к прошлой задаче. Вердикт о другой задаче подстройку не включает."""
    return verdict is not None and verdict.task_id in (None, previous.id)


def _reason(task: Task, previous: Task | None) -> str:
    if previous is None:
        return "start"
    if task.difficulty > previous.difficulty:
        return "harder"
    if task.difficulty < previous.difficulty:
        return "easier"
    return "same"


async def _by_id(store: PlatformStore, task_id: str) -> Done:
    task = await store.get_task(task_id)
    if task is None:
        return Done(
            outcome="empty", events=[BlockEvent(type="no_tasks", data={"task_id": task_id})]
        )
    return _chosen(task, "task_id")


def _chosen(task: Task, reason: str) -> Done:
    event = BlockEvent(
        type="task_chosen",
        data={"task_id": task.id, "difficulty": task.difficulty, "reason": reason},
    )
    return Done(outputs={"task": task.model_dump(mode="json")}, events=[event])
