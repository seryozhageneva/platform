"""Состояние запуска и интерфейс хранилища запусков (ADR 0006).

Движок знает только этот интерфейс. В тестах движка хранилище — словарь в памяти, в
платформе — таблицы PostgreSQL (`backend/models/run_store.py`).

Кроме самих значений выходов состояние помнит порядок, в котором они записаны (ADR 0009):
по нему привязка «несколько ссылок на выбор» находит значение, записанное последним.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

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
    # Выходы «узел.порт» в порядке записи, от самого старого к самому свежему. Нужен
    # отдельным списком: порядок ключей в `ports` при сохранении в базу не сохраняется.
    write_order: list[str] = []
    # Сколько раз пройден узел с ограничителем: узел -> число.
    counters: dict[str, int] = {}
    # На каком элементе списка стоит узел «для каждого»: узел -> номер элемента, с нуля.
    item_index: dict[str, Annotated[int, Field(ge=0)]] = {}
    waiting: list[WaitingFor] = []
    error: str | None = None

    @model_validator(mode="after")
    def _order_matches_ports(self) -> Self:
        repeated = sorted({ref for ref in self.write_order if self.write_order.count(ref) > 1})
        if repeated:
            raise ValueError(f"выход повторяется в порядке записи: {', '.join(repeated)}")
        unknown = [ref for ref in self.write_order if not self._is_written(ref)]
        if unknown:
            raise ValueError(
                f"в порядке записи есть выход, которого нет в `ports`: {', '.join(unknown)}"
            )
        return self

    def write(self, node_id: str, outputs: Mapping[str, Any]) -> None:
        """Записывает выходы узла. Каждый записанный выход становится самым свежим."""
        self.ports[node_id] = {**self.ports.get(node_id, {}), **outputs}
        refs = [f"{node_id}.{port}" for port in outputs]
        self.write_order = [ref for ref in self.write_order if ref not in refs] + refs

    def latest(self, refs: Sequence[str]) -> str | None:
        """Какая из ссылок записана последней; None — ни одна не записана.

        У ссылки «узел.порт.поле» смотрится выход «узел.порт»: поле читается из его
        значения. Выход, которого нет в порядке записи, считается самым старым: так
        читаются запуски, сохранённые до появления этого поля.
        """
        written = [ref for ref in refs if self._is_written(_output(ref))]
        if not written:
            return None
        age = {ref: index for index, ref in enumerate(self.write_order)}
        return max(written, key=lambda ref: age.get(_output(ref), -1))

    def _is_written(self, ref: str) -> bool:
        node_id, _, port = ref.partition(".")
        return port in self.ports.get(node_id, {})


def _output(ref: str) -> str:
    """Выход «узел.порт», на который указывает ссылка «узел.порт» или «узел.порт.поле»."""
    return ".".join(ref.split(".")[:2])


@runtime_checkable
class RunStore(Protocol):
    async def load(self, run_id: str) -> RunState | None: ...

    async def save(self, state: RunState) -> None: ...

    async def append_events(self, run_id: str, node_id: str, events: list[BlockEvent]) -> None: ...
