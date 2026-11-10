"""Хранилище запусков на PostgreSQL — реализация интерфейса `RunStore` из контракта (ADR 0006).

Состояние запуска лежит в таблице `runs`: то, по чему ищет кабинет, — отдельными столбцами,
остальное — одним JSON-полем `state` (ADR 0007). Журнал событий — таблица `events`.
"""

import uuid
from typing import Any

from sqlalchemy import and_, cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH, insert

from backend.core.contracts.run import BlockEvent
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.models.db import Sessions
from backend.models.tables import (
    ApprovalRow,
    EventRow,
    PipelineVersionRow,
    RunRow,
    SubmissionRow,
    UserRow,
)

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
    def __init__(self, sessions: Sessions, *, assignment_id: uuid.UUID | None = None) -> None:
        self._sessions = sessions
        self._assignment_id = assignment_id
        self._pending_submissions: list[SubmissionRow] = []
        self._pending_decision: tuple[uuid.UUID, str, dict[str, Any]] | None = None

    def stage_approval(
        self, approval_id: uuid.UUID, outcome: str, response: dict[str, Any]
    ) -> None:
        self._pending_decision = (approval_id, outcome, response)

    def stage_submission(self, row: SubmissionRow) -> None:
        """Работы сохранятся с успешным шагом, который принял ответы."""
        self._pending_submissions.append(row)

    async def for_teacher(self, teacher_id: uuid.UUID) -> list[dict[str, Any]]:
        waiting_nodes = func.jsonb_path_query_array(
            RunRow.state, cast("$.waiting[*].node_id", JSONPATH), type_=JSONB
        )
        waiting_roles = func.jsonb_path_query_array(
            RunRow.state, cast("$.waiting[*].who", JSONPATH), type_=JSONB
        )
        query = (
            select(
                RunRow.id,
                RunRow.pipeline_id,
                PipelineVersionRow.graph["name"].as_string().label("pipeline_name"),
                RunRow.pipeline_version,
                UserRow.name.label("student_name"),
                RunRow.status,
                RunRow.state["current"].label("current"),
                waiting_nodes.label("waiting_nodes"),
                waiting_roles.label("waiting_roles"),
                RunRow.error,
                RunRow.updated_at,
            )
            .join(
                PipelineVersionRow,
                (PipelineVersionRow.pipeline_id == RunRow.pipeline_id)
                & (PipelineVersionRow.version == RunRow.pipeline_version),
            )
            .outerjoin(
                UserRow, (UserRow.id == RunRow.student_id) & (UserRow.owner_id == teacher_id)
            )
            .where(RunRow.teacher_id == teacher_id)
            .order_by(RunRow.updated_at.desc(), RunRow.id.desc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(query)).mappings()
            result = []
            for row in rows:
                summary = dict(row)
                summary["current"] = summary["current"] or []
                summary["waiting"] = [
                    {"node_id": node, "who": who}
                    for node, who in zip(
                        summary.pop("waiting_nodes"), summary.pop("waiting_roles"), strict=True
                    )
                ]
                result.append(summary)
            return result

    async def load(self, run_id: str) -> RunState | None:
        key = _uuid_or_none(run_id)
        if key is None:
            return None
        async with self._sessions() as session:
            row = await session.get(RunRow, key)
        return self._state(row) if row else None

    async def load_with_approval(
        self, run_id: uuid.UUID
    ) -> tuple[RunState, uuid.UUID | None] | None:
        # Один запрос читает согласованную пару: экран паузы и его идентификатор.
        query = (
            select(RunRow, ApprovalRow.id)
            .outerjoin(
                ApprovalRow,
                and_(ApprovalRow.run_id == RunRow.id, ApprovalRow.answered_at.is_(None)),
            )
            .where(RunRow.id == run_id)
        )
        async with self._sessions() as session:
            result = (await session.execute(query)).one_or_none()
        return (self._state(result[0]), result[1]) if result else None

    @staticmethod
    def _state(row: RunRow) -> RunState:
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
            assignment_id=self._assignment_id,
            pipeline_id=_uuid(state.pipeline_id, "pipeline_id"),
            pipeline_version=state.pipeline_version,
            student_id=_uuid(state.student_id, "student_id"),
            teacher_id=_uuid(state.teacher_id, "teacher_id"),
            **changing,
        )
        query = query.on_conflict_do_update(
            index_elements=[RunRow.id], set_={**changing, "updated_at": func.now()}
        )
        pending, self._pending_submissions = self._pending_submissions, []
        decision, self._pending_decision = self._pending_decision, None
        async with self._sessions.begin() as session:
            await session.execute(query)
            if state.status is not RunStatus.ERROR:
                session.add_all(pending)
                if decision is not None:
                    approval_id, outcome, response = decision
                    closed = await session.scalar(
                        update(ApprovalRow)
                        .where(
                            ApprovalRow.id == approval_id,
                            ApprovalRow.run_id == uuid.UUID(state.run_id),
                            ApprovalRow.answered_at.is_(None),
                        )
                        .values(outcome=outcome, response=response, answered_at=func.now())
                        .returning(ApprovalRow.id)
                    )
                    if closed is None:
                        raise RuntimeError("подтверждение уже закрыто")
            if state.status is RunStatus.WAITING and state.teacher_id is not None:
                for waiting in state.waiting:
                    if waiting.who == "teacher" and waiting.screen is ScreenType.REVIEW_TABLE:
                        await session.execute(
                            insert(ApprovalRow)
                            .values(
                                run_id=uuid.UUID(state.run_id),
                                node_id=waiting.node_id,
                                teacher_id=uuid.UUID(state.teacher_id),
                                snapshot=waiting.data,
                            )
                            .on_conflict_do_nothing(
                                index_elements=[ApprovalRow.run_id],
                                index_where=ApprovalRow.answered_at.is_(None),
                            )
                        )

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
