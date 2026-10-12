"""Репозиторий пайплайнов и их версий.

Каждое сохранение — новая версия; старые не меняются, потому что на них ссылаются идущие
запуски (ADR 0007). Граф хранится в том же виде, что и файл пайплайна из контракта.
Проверку стыковки портов делает не репозиторий, а валидатор (задача 06).
"""

import uuid
from typing import Any

from sqlalchemy import select

from backend.core.contracts.pipeline import Pipeline
from backend.models.db import Sessions
from backend.models.tables import PipelineRow, PipelineVersionRow


class PipelineRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(self, owner_id: uuid.UUID, pipeline: Pipeline) -> PipelineRow:
        """Новый пайплайн преподавателя; граф становится версией 1."""
        row = PipelineRow(owner_id=owner_id, slug=pipeline.id, name=pipeline.name, latest_version=1)
        async with self._sessions.begin() as session:
            session.add(row)
            await session.flush()
            session.add(PipelineVersionRow(pipeline_id=row.id, version=1, graph=_dump(pipeline)))
        return row

    async def save_version(
        self, owner_id: uuid.UUID, pipeline_id: uuid.UUID, pipeline: Pipeline
    ) -> int:
        """Сохраняет граф новой версией и возвращает её номер."""
        query = (
            select(PipelineRow)
            .where(PipelineRow.id == pipeline_id, PipelineRow.owner_id == owner_id)
            # Строка блокируется до конца транзакции: два сохранения не получат один номер.
            .with_for_update()
        )
        async with self._sessions.begin() as session:
            row = await session.scalar(query)
            if row is None:
                raise LookupError("пайплайн не найден")
            row.latest_version += 1
            row.slug, row.name = pipeline.id, pipeline.name
            session.add(
                PipelineVersionRow(
                    pipeline_id=row.id, version=row.latest_version, graph=_dump(pipeline)
                )
            )
            return row.latest_version

    async def get(self, owner_id: uuid.UUID, pipeline_id: uuid.UUID) -> PipelineRow | None:
        query = select(PipelineRow).where(
            PipelineRow.id == pipeline_id, PipelineRow.owner_id == owner_id
        )
        async with self._sessions() as session:
            return await session.scalar(query)

    async def list_pipelines(self, owner_id: uuid.UUID) -> list[PipelineRow]:
        """Только пайплайны этого преподавателя."""
        query = (
            select(PipelineRow)
            .where(PipelineRow.owner_id == owner_id)
            .order_by(PipelineRow.created_at, PipelineRow.name)
        )
        async with self._sessions() as session:
            return list(await session.scalars(query))

    async def load(self, pipeline_id: uuid.UUID, version: int | None = None) -> Pipeline | None:
        """Граф указанной версии, а без номера — последней.

        Владельца не спрашивает: так пайплайн читается для запуска, у которого версия уже
        записана. В кабинете сначала проверяют доступ через `get`.
        """
        query = select(PipelineVersionRow.graph).where(
            PipelineVersionRow.pipeline_id == pipeline_id
        )
        if version is None:
            query = query.order_by(PipelineVersionRow.version.desc()).limit(1)
        else:
            query = query.where(PipelineVersionRow.version == version)
        async with self._sessions() as session:
            graph = await session.scalar(query)
        return None if graph is None else Pipeline.model_validate(graph)


def _dump(pipeline: Pipeline) -> dict[str, Any]:
    return pipeline.model_dump(mode="json", by_alias=True)
