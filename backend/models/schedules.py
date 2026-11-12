"""Настройки расписания; граф и cron хранятся в версии пайплайна."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.models.db import Sessions
from backend.models.tables import PipelineRow, ScheduleRow


class ScheduleRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def get(self, pipeline_id: UUID) -> ScheduleRow | None:
        async with self._sessions() as session:
            return await session.get(ScheduleRow, pipeline_id)

    async def save(
        self, pipeline_id: UUID, version: int, *, enabled: bool, params: dict[str, Any]
    ) -> ScheduleRow | None:
        async with self._sessions.begin() as session:
            current_version = await session.scalar(
                select(PipelineRow.latest_version)
                .where(PipelineRow.id == pipeline_id)
                .with_for_update()
            )
            if current_version != version:
                return None
            values = {"enabled": enabled, "params": params}
            query = insert(ScheduleRow).values(pipeline_id=pipeline_id, **values)
            return await session.scalar(
                query.on_conflict_do_update(
                    index_elements=[ScheduleRow.pipeline_id], set_=values
                ).returning(ScheduleRow)
            )

    async def candidates(self, minute: datetime) -> list[tuple[ScheduleRow, PipelineRow]]:
        query = (
            select(ScheduleRow, PipelineRow)
            .join(PipelineRow, PipelineRow.id == ScheduleRow.pipeline_id)
            .where(
                ScheduleRow.enabled,
                or_(ScheduleRow.last_fired_at.is_(None), ScheduleRow.last_fired_at < minute),
            )
        )
        async with self._sessions() as session:
            return [(schedule, pipeline) for schedule, pipeline in await session.execute(query)]
