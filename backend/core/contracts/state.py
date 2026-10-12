"""Состояние запуска и интерфейс хранилища запусков (ADR 0006).

Движок знает только этот интерфейс. В тестах движка хранилище — словарь в памяти, в
платформе — таблицы PostgreSQL; реализация появится в задачах 03 и 04.
"""

from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from backend.core.contracts.base import Strict
from backend.core.contracts.run import BlockEvent
from backend.core.contracts.screens import ScreenType


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"


class WaitingFor(Strict):
    """На каком узле запуск стоит на паузе и какой экран показан человеку."""

    node_id: str
    who: Literal["student", "teacher"]
    screen: ScreenType
    data: dict[str, Any]


class RunState(Strict):
    run_id: str
    pipeline_id: str
    # Запуск привязан к версии пайплайна, с которой стартовал.
    pipeline_version: int
    status: RunStatus = RunStatus.RUNNING
    params: dict[str, Any] = {}
    student_id: str | None = None
    teacher_id: str | None = None
    # Узлы, которые выполняются сейчас или ждут человека.
    current: list[str] = []
    # Последнее значение каждого выхода: узел -> порт -> значение.
    ports: dict[str, dict[str, Any]] = {}
    # Сколько раз пройден узел с ограничителем: узел -> число.
    counters: dict[str, int] = {}
    waiting: list[WaitingFor] = []
    error: str | None = None


@runtime_checkable
class RunStore(Protocol):
    async def load(self, run_id: str) -> RunState | None: ...

    async def save(self, state: RunState) -> None: ...

    async def append_events(self, run_id: str, node_id: str, events: list[BlockEvent]) -> None: ...
