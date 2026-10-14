"""Формы запросов и ответов API v1.

По ним FastAPI проверяет ответы и строит описание OpenAPI, из которого фронтенд получит
свои типы (задача 13). Граф пайплайна передаётся в формате контракта — моделью `Pipeline`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import CheckMethod
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.core.contracts.wiring import Problem
from backend.models.tables import EventRow, PipelineRow, TaskRow, TaskStatus


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


# Тема и предмет сравниваются точно, поэтому пробелы по краям обрезаются ещё при записи.
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Чем проверяется задача каждого способа: без этого поля проверка в уроке упадёт.
NEEDED_FOR_CHECK = {
    CheckMethod.SHORT_ANSWER: ("answer", "ответ"),
    CheckMethod.CODE: ("tests", "тесты"),
    CheckMethod.LONG_ANSWER: ("rubric", "рубрика"),
}


class TaskFields(BaseModel):
    """Поля задачи банка — те же, что у типа `Task` из контракта, плюс статус."""

    subject: Label
    topic: Label
    difficulty: int = Field(ge=1)
    statement: str = Field(min_length=1, description="Условие: Markdown и LaTeX")
    check_method: CheckMethod
    answer: str | None = None
    solution: str | None = None
    tests: str | None = None
    rubric: str | None = None
    # Задачу, которую преподаватель пишет сам, он и подтверждает. Черновики — для задач,
    # которые сочинил ИИ: их запишет блок после Подтверждения (задача 22).
    status: TaskStatus = TaskStatus.APPROVED


class TaskIn(TaskFields):
    """Задача банка, как её присылает преподаватель (ADR 0015)."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _approved_can_be_checked(self) -> Self:
        field, title = NEEDED_FOR_CHECK[self.check_method]
        if self.status is TaskStatus.APPROVED and not getattr(self, field):
            raise ValueError(
                f"у подтверждённой задачи со способом проверки «{self.check_method.value}» "
                f"должно быть поле «{field}» ({title}); неполную задачу сохраните черновиком"
            )
        return self


class TaskOut(TaskFields):
    """Задача банка в ответе: поля, номер и время."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: TaskRow) -> "TaskOut":
        return cls(
            id=row.id,
            subject=row.subject,
            topic=row.topic,
            difficulty=row.difficulty,
            statement=row.statement,
            check_method=CheckMethod(row.check_method),
            answer=row.answer,
            solution=row.solution,
            tests=row.tests,
            rubric=row.rubric,
            status=TaskStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
