"""Формы запросов и ответов API v1.

По ним FastAPI проверяет ответы и строит описание OpenAPI, из которого фронтенд получит
свои типы (задача 13). Граф пайплайна передаётся в формате контракта — моделью `Pipeline`.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.core.contracts.wiring import Problem
from backend.models.tables import EventRow, PipelineRow


class ProblemOut(BaseModel):
    """Одна причина отказа или предупреждение."""

    # Узел пайплайна, к которому относится замечание; пусто — оно не про узел.
    node: str | None = None
    code: str
    message: str

    @classmethod
    def of(cls, problem: Problem) -> "ProblemOut":
        return cls(node=problem.node, code=problem.code, message=problem.message)


class ErrorOut(BaseModel):
    """Ответ на запрос, который не выполнен: что случилось и список причин."""

    message: str
    problems: list[ProblemOut] = []


class PipelineSaved(BaseModel):
    id: uuid.UUID
    version: int
    # С предупреждениями пайплайн сохраняется; редактор их показывает (ADR 0011).
    warnings: list[ProblemOut] = []


class PipelineSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    latest_version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: PipelineRow) -> "PipelineSummary":
        return cls(
            id=row.id,
            slug=row.slug,
            name=row.name,
            latest_version=row.latest_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class PipelineDetail(PipelineSummary):
    graph: Pipeline


class LaunchRequest(BaseModel):
    """Значения параметров пайплайна; незаполненные берутся по умолчанию."""

    # Незнакомое поле — ошибка, как в контракте: опечатка в `params` не должна
    # молча запустить пайплайн со значениями по умолчанию.
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = {}


class WaitingOut(BaseModel):
    node_id: str
    who: str
    screen: ScreenType


class RunOut(BaseModel):
    """Состояние запуска без данных портов: что из них показывать, решает кабинет."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    pipeline_version: int
    status: RunStatus
    params: dict[str, Any]
    current: list[str]
    waiting: list[WaitingOut]
    error: str | None

    @classmethod
    def of(cls, state: RunState) -> "RunOut":
        return cls(
            id=uuid.UUID(state.run_id),
            pipeline_id=uuid.UUID(state.pipeline_id),
            pipeline_version=state.pipeline_version,
            status=state.status,
            params=state.params,
            current=state.current,
            waiting=[
                WaitingOut(node_id=item.node_id, who=item.who, screen=item.screen)
                for item in state.waiting
            ],
            error=state.error,
        )


class EventOut(BaseModel):
    """Запись журнала событий запуска."""

    id: int
    node_id: str
    type: str
    data: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, row: EventRow) -> "EventOut":
        return cls(
            id=row.id, node_id=row.node_id, type=row.type, data=row.data, created_at=row.created_at
        )
