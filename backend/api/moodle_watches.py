"""Настройки запуска пайплайна по событию Moodle для его преподавателя (ADR 0034)."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schedules import ScheduleSettings, teacher_pipeline
from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import TriggerType
from backend.models.tables import MoodleWatchRow
from backend.triggers.manual import launch_problems
from backend.triggers.moodle_graph import moodle_launch, poll_minutes

router = APIRouter(prefix="/pipelines", tags=["Событие Moodle"], responses=REFUSALS)


class MoodleWatchUpdate(ScheduleSettings):
    expected_version: int


class MoodleWatchDetails(ScheduleSettings):
    # Как часто опрашивается Moodle; None — в графе нет запуска по событию Moodle.
    poll_minutes: int | None
    last_polled_at: datetime | None = None
    # Последняя ошибка опроса, понятная преподавателю; None — опрос прошёл.
    last_error: str | None = None
    # Сколько сдач уже взяли запуски по событию: повторно они не берутся.
    seen_submissions: int = 0


def _minutes(graph: Pipeline) -> int | None:
    launch = moodle_launch(graph)
    return None if launch is None else poll_minutes(launch)


def _details(minutes: int | None, watch: MoodleWatchRow | None, seen: int) -> MoodleWatchDetails:
    if watch is None:
        return MoodleWatchDetails(poll_minutes=minutes, enabled=False, seen_submissions=seen)
    return MoodleWatchDetails(
        poll_minutes=minutes,
        enabled=watch.enabled and minutes is not None,
        params=watch.params,
        last_polled_at=watch.last_polled_at,
        last_error=watch.last_error,
        seen_submissions=seen,
    )


@router.get("/{pipeline_id}/moodle-watch", summary="Настройки запуска по событию Moodle")
async def get_moodle_watch(
    pipeline_id: UUID, teacher: Teacher, assembly: Assembled
) -> MoodleWatchDetails:
    _, graph = await teacher_pipeline(pipeline_id, teacher, assembly)
    watches = assembly.moodle_watches
    return _details(
        _minutes(graph), await watches.get(pipeline_id), await watches.seen_count(pipeline_id)
    )


@router.put("/{pipeline_id}/moodle-watch", summary="Сохранить настройки запуска по событию Moodle")
async def put_moodle_watch(
    pipeline_id: UUID, request: MoodleWatchUpdate, teacher: Teacher, assembly: Assembled
) -> MoodleWatchDetails:
    row, graph = await teacher_pipeline(pipeline_id, teacher, assembly)
    if row.latest_version != request.expected_version:
        raise ApiError(409, "версия пайплайна изменилась, откройте его заново")
    params = {name: value for name, value in request.params.items() if value is not None}
    if request.enabled:
        problems = launch_problems(assembly, graph, TriggerType.MOODLE_EVENT, params)
        if problems:
            raise ApiError(422, "запуск по событию Moodle нельзя включить", problems)
    watch = await assembly.moodle_watches.save(
        pipeline_id, row.latest_version, enabled=request.enabled, params=params
    )
    if watch is None:
        raise ApiError(409, "версия пайплайна изменилась, откройте его заново")
    seen = await assembly.moodle_watches.seen_count(pipeline_id)
    return _details(_minutes(graph), watch, seen)
