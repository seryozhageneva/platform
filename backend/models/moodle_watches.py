"""Наблюдение за Moodle: настройки опроса и обработанные сдачи (ADR 0034).

Граф и частота опроса хранятся в версии пайплайна, здесь — только включённость,
параметры, время последнего опроса и сдачи, для которых уже создан запуск.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from backend.models.db import Sessions
from backend.models.tables import MoodleSeenRow, MoodleWatchRow, PipelineRow

# Сдача Moodle: номер и время сдачи (Unix-время). После доработки время меняется.
SubmissionMark = tuple[int, int]


class MoodleWatchRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def get(self, pipeline_id: UUID) -> MoodleWatchRow | None:
        async with self._sessions() as session:
            return await session.get(MoodleWatchRow, pipeline_id)

    async def save(
        self, pipeline_id: UUID, version: int, *, enabled: bool, params: dict[str, Any]
    ) -> MoodleWatchRow | None:
        """Сохраняет настройки, если версия пайплайна не изменилась; иначе None."""
        async with self._sessions.begin() as session:
            current_version = await session.scalar(
                select(PipelineRow.latest_version)
                .where(PipelineRow.id == pipeline_id)
                .with_for_update()
            )
            if current_version != version:
                return None
            values = {"enabled": enabled, "params": params}
            query = insert(MoodleWatchRow).values(pipeline_id=pipeline_id, **values)
            return await session.scalar(
                query.on_conflict_do_update(
                    index_elements=[MoodleWatchRow.pipeline_id], set_=values
                ).returning(MoodleWatchRow)
            )

    async def enabled(self) -> list[tuple[MoodleWatchRow, PipelineRow]]:
        query = (
            select(MoodleWatchRow, PipelineRow)
            .join(PipelineRow, PipelineRow.id == MoodleWatchRow.pipeline_id)
            .where(MoodleWatchRow.enabled)
        )
        async with self._sessions() as session:
            return [(watch, pipeline) for watch, pipeline in await session.execute(query)]

    async def claim_poll(self, watch: MoodleWatchRow, now: datetime) -> bool:
        """Отмечает начало опроса. False — его уже начал другой рабочий процесс."""
        previous = watch.last_polled_at
        condition = (
            MoodleWatchRow.last_polled_at.is_(None)
            if previous is None
            else MoodleWatchRow.last_polled_at == previous
        )
        async with self._sessions.begin() as session:
            claimed = await session.scalar(
                update(MoodleWatchRow)
                .where(
                    MoodleWatchRow.pipeline_id == watch.pipeline_id,
                    MoodleWatchRow.enabled,
                    condition,
                )
                .values(last_polled_at=now)
                .returning(MoodleWatchRow.pipeline_id)
            )
        return claimed is not None

    async def record_error(self, pipeline_id: UUID, error: str | None) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(MoodleWatchRow)
                .where(MoodleWatchRow.pipeline_id == pipeline_id)
                .values(last_error=error)
            )

    async def unseen(
        self, pipeline_id: UUID, marks: Iterable[SubmissionMark]
    ) -> list[SubmissionMark]:
        """Те сдачи из `marks`, для которых запуска ещё не было, в том же порядке."""
        marks = list(marks)
        if not marks:
            return []
        query = select(MoodleSeenRow.submission_id, MoodleSeenRow.submitted_at).where(
            MoodleSeenRow.pipeline_id == pipeline_id,
            MoodleSeenRow.submission_id.in_({number for number, _ in marks}),
        )
        async with self._sessions() as session:
            seen = {(number, at) for number, at in await session.execute(query)}
        return [mark for mark in marks if mark not in seen]

    async def seen_count(self, pipeline_id: UUID) -> int:
        query = select(func.count()).where(MoodleSeenRow.pipeline_id == pipeline_id)
        async with self._sessions() as session:
            return int(await session.scalar(query) or 0)
