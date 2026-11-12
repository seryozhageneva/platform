"""Настройки запуска пайплайна по расписанию для его преподавателя."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import JsonValue

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.core.contracts.base import Strict
from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import TriggerType
from backend.models.tables import PipelineRow, ScheduleRow
from backend.triggers.manual import launch_problems
from backend.triggers.schedule import schedule_expression

router = APIRouter(prefix="/pipelines", tags=["Расписания"], responses=REFUSALS)


class ScheduleSettings(Strict):
    enabled: bool
    params: dict[str, JsonValue] = {}


class ScheduleUpdate(ScheduleSettings):
    expected_version: int


class ScheduleDetails(ScheduleSettings):
    cron: str | None
    last_fired_at: datetime | None = None


def _details(cron: str | None, settings: ScheduleRow | None) -> ScheduleDetails:
    if settings is None:
        return ScheduleDetails(cron=cron, enabled=False)
    return ScheduleDetails(
        cron=cron,
        enabled=settings.enabled and cron is not None,
        params=settings.params,
        last_fired_at=settings.last_fired_at,
    )


async def _pipeline(
    pipeline_id: UUID, teacher: Teacher, assembly: Assembled
) -> tuple[PipelineRow, Pipeline]:
    row = await assembly.pipelines.get(teacher.id, pipeline_id)
    graph = None if row is None else await assembly.pipelines.load(row.id, row.latest_version)
    if row is None or graph is None:
        raise ApiError(404, "пайплайн не найден")
    return row, graph


@router.get("/{pipeline_id}/schedule", summary="Настройки расписания пайплайна")
async def get_schedule(pipeline_id: UUID, teacher: Teacher, assembly: Assembled) -> ScheduleDetails:
    _, graph = await _pipeline(pipeline_id, teacher, assembly)
    return _details(schedule_expression(graph), await assembly.schedules.get(pipeline_id))


@router.put("/{pipeline_id}/schedule", summary="Сохранить настройки расписания")
async def put_schedule(
    pipeline_id: UUID, request: ScheduleUpdate, teacher: Teacher, assembly: Assembled
) -> ScheduleDetails:
    row, graph = await _pipeline(pipeline_id, teacher, assembly)
    if row.latest_version != request.expected_version:
        raise ApiError(409, "версия пайплайна изменилась, откройте его заново")
    cron = schedule_expression(graph)
    params = {name: value for name, value in request.params.items() if value is not None}
    if request.enabled:
        problems = launch_problems(assembly, graph, TriggerType.SCHEDULE, params)
        if problems:
            raise ApiError(422, "расписание нельзя включить", problems)
    settings = await assembly.schedules.save(
        pipeline_id, row.latest_version, enabled=request.enabled, params=params
    )
    if settings is None:
        raise ApiError(409, "версия пайплайна изменилась, откройте его заново")
    return _details(cron, settings)
