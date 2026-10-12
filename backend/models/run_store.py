"""Хранилище запусков на PostgreSQL — реализация интерфейса `RunStore` из контракта (ADR 0006).

Состояние запуска лежит в таблице `runs`: то, по чему ищет кабинет, — отдельными столбцами,
остальное — одним JSON-полем `state` (ADR 0007). Журнал событий — таблица `events`.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from backend.core.contracts.run import BlockEvent
from backend.core.contracts.state import RunState
from backend.models.db import Sessions
from backend.models.tables import EventRow, RunRow

# Поля состояния, у которых в таблице свой столбец. Все прочие поля `RunState` уходят в
# `state`, поэтому новое поле состояния не требует миграции.
_COLUMNS = {
    "run_id",
    "pipeline_id",
    "pipeline_version",
    "status",
    "student_id",
    "teacher_id",
    "error",
}


class PgRunStore:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def load(self, run_id: str) -> RunState | None:
        key = _uuid_or_none(run_id)
        if key is None:
            return None
        async with self._sessions() as session:
            row = await session.get(RunRow, key)
        if row is None:
            return None
        return RunState.model_validate(
            {
                "run_id": str(row.id),
                "pipeline_id": str(row.pipeline_id),
                "pipeline_version": row.pipeline_version,
                "status": row.status,
                "student_id": _text(row.student_id),
                "teacher_id": _text(row.teacher_id),
                "error": row.error,
                **row.state,
            }
        )

    async def save(self, state: RunState) -> None:
        """Создаёт запуск или обновляет его.

        Пайплайн, его версия, ученик и преподаватель записываются один раз, при создании:
        запуск привязан к версии, с которой стартовал.
        """
        dumped = state.model_dump(mode="json")
        changing: dict[str, Any] = {
            "status": state.status.value,
            "error": state.error,
            "state": {name: value for name, value in dumped.items() if name not in _COLUMNS},
        }
        query = insert(RunRow).values(
            id=_uuid(state.run_id, "run_id"),
            pipeline_id=_uuid(state.pipeline_id, "pipeline_id"),
            pipeline_version=state.pipeline_version,
            student_id=_uuid(state.student_id, "student_id"),
            teacher_id=_uuid(state.teacher_id, "teacher_id"),
            **changing,
        )
        query = query.on_conflict_do_update(
            index_elements=[RunRow.id], set_={**changing, "updated_at": func.now()}
        )
        async with self._sessions.begin() as session:
            await session.execute(query)

    async def append_events(self, run_id: str, node_id: str, events: list[BlockEvent]) -> None:
        if not events:
            return
        key = _uuid(run_id, "run_id")
        # Данные события переводятся в JSON так же, как состояние: дата становится строкой.
        rows = [
            EventRow(
                run_id=key,
                node_id=node_id,
                type=event.type,
                data=event.model_dump(mode="json")["data"],
            )
            for event in events
        ]
        async with self._sessions.begin() as session:
            session.add_all(rows)

    async def events(self, run_id: str) -> list[EventRow]:
        """Журнал запуска в том порядке, в каком события записаны."""
        key = _uuid_or_none(run_id)
        if key is None:
            return []
        query = select(EventRow).where(EventRow.run_id == key).order_by(EventRow.id)
        async with self._sessions() as session:
            return list(await session.scalars(query))


def _uuid(value: str | None, what: str) -> uuid.UUID | None:
    """В контракте идентификаторы — строки, в базе — UUID."""
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"{what}: «{value}» — не идентификатор из базы (ожидался UUID)") from None


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _text(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
