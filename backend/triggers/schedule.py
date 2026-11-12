"""Проверка расписаний и постановка подходящих запусков в очередь."""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import Event, TriggerType
from backend.core.cron import matches_cron, valid_cron
from backend.models.run_store import ScheduleChanged
from backend.triggers.assembly import Assembly
from backend.triggers.manual import launch_problems
from backend.triggers.queue import EnqueueLaunch, QueueUnavailable

logger = logging.getLogger(__name__)


def schedule_expression(pipeline: Pipeline) -> str | None:
    return next(
        (
            launch.cron
            for launch in pipeline.trigger().launches
            if launch.type is TriggerType.SCHEDULE
        ),
        None,
    )


async def enqueue_schedules(assembly: Assembly, enqueue: EnqueueLaunch, *, now: datetime) -> None:
    minute = now.astimezone(UTC).replace(second=0, microsecond=0)
    for schedule, row in await assembly.schedules.candidates(minute):
        pipeline = await assembly.pipelines.load(row.id, row.latest_version)
        if pipeline is None:
            continue
        cron = schedule_expression(pipeline)
        if not cron or not valid_cron(cron) or not matches_cron(cron, minute):
            continue
        if launch_problems(assembly, pipeline, TriggerType.SCHEDULE, schedule.params):
            logger.warning("Пайплайн %s не прошёл проверку запуска по расписанию", row.id)
            continue
        state = assembly.engine().prepare(
            pipeline,
            run_id=str(uuid4()),
            pipeline_id=str(row.id),
            pipeline_version=row.latest_version,
            event=Event(trigger=TriggerType.SCHEDULE, occurred_at=minute),
            params=schedule.params,
            teacher_id=str(row.owner_id),
        )
        try:
            async with assembly.runs.queue_launch(
                state,
                pipeline.trigger().id,
                schedule_minute=minute,
                schedule_params=schedule.params,
            ):
                await enqueue(UUID(state.run_id))
        except ScheduleChanged:
            continue
        except QueueUnavailable:
            logger.warning("Очередь не приняла запуск пайплайна %s по расписанию", row.id)
