"""Ответ человека запуску, который стоит на паузе (ADR 0016).

Общий путь для всех, кто отвечает: сейчас — преподаватель через API (`backend/api/runs.py`),
в задаче 14 — ученик из своего кабинета. Кто имеет право отвечать на этот запуск, решает
тот, кто вызывает: здесь это уже проверено.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from backend.core.contracts.state import RunState, RunStatus
from backend.triggers.assembly import Assembly


class NotWaiting(Exception):
    """Запуск не ждёт ответа на этом узле: уже ответили, он закончился или ждёт на другом."""


async def answer_run(
    assembly: Assembly, state: RunState, node_id: str, response: Mapping[str, Any]
) -> RunState:
    """Передаёт ответ узлу, на котором стоит запуск, и выполняет запуск дальше.

    Возвращает новое состояние: запуск закончился, снова встал на паузу или остановился с
    ошибкой. Ответ не по форме экрана — `ResponseRejected` из движка, состояние не меняется.
    """
    if state.status is not RunStatus.WAITING or all(
        item.node_id != node_id for item in state.waiting
    ):
        raise NotWaiting(f"запуск не ждёт ответа на узле «{node_id}»")
    # Запуск продолжается на той версии пайплайна, с которой стартовал (ADR 0007), даже
    # если преподаватель с тех пор пайплайн пересохранил.
    pipeline = await assembly.pipelines.load(uuid.UUID(state.pipeline_id), state.pipeline_version)
    if pipeline is None:
        raise LookupError(f"версии {state.pipeline_version} пайплайна запуска нет в базе")
    return await assembly.engine().respond(pipeline, state.run_id, node_id, response)
