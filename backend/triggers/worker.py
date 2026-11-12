"""Фоновый процесс запусков: uv run arq backend.triggers.worker.WorkerSettings."""

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import cron

from backend.core.contracts.ports import Event
from backend.core.contracts.state import RunStatus
from backend.triggers.assembly import Assembly, open_assembly
from backend.triggers.moodle_event import poll_moodle
from backend.triggers.queue import (
    QUEUE_NAME,
    RUN_TIMEOUT,
    LaunchQueue,
    QueueSettings,
    serialize_job,
)
from backend.triggers.schedule import enqueue_schedules

logger = logging.getLogger(__name__)


async def run_manual(assembly: Assembly, run_id: UUID, *, timeout: float = RUN_TIMEOUT) -> None:
    """Исполняет подготовленный запуск. Имя задания в Redis сохранено для старых запусков."""
    # Совпадает с ключом транзакции, которая записывает запуск, и с ключом ответа на паузе.
    async with assembly.assignments.lock(run_id, wait=True):
        state = await assembly.runs.load(str(run_id))
        if state is None or state.status is not RunStatus.RUNNING:
            return
        trigger_id = await assembly.runs.queued_trigger(run_id)
        if trigger_id is None:
            return
        try:
            async with asyncio.timeout(timeout):
                pipeline = await assembly.pipelines.load(
                    UUID(state.pipeline_id), state.pipeline_version
                )
                if pipeline is None:
                    raise LookupError("версия пайплайна не найдена")
                event = Event.model_validate(state.ports[trigger_id]["event"])
                await assembly.engine().execute_prepared(pipeline, state, event.trigger.value)
        except asyncio.CancelledError:
            await assembly.runs.fail_queued(run_id, trigger_id, "Рабочий процесс остановлен")
            raise
        except Exception as error:
            logger.error("Фоновый запуск %s остановлен: %s", run_id, type(error).__name__)
            message = (
                "Истекло время выполнения фонового запуска"
                if isinstance(error, TimeoutError)
                else "Рабочий процесс не смог выполнить запуск"
            )
            await assembly.runs.fail_queued(run_id, trigger_id, message)


async def execute_manual(ctx: dict[str, Any], run_id: str) -> None:
    await run_manual(ctx["assembly"], UUID(run_id))


async def check_schedules(ctx: dict[str, Any]) -> None:
    redis = ctx["redis"]
    await enqueue_schedules(
        ctx["assembly"],
        LaunchQueue(redis, name=redis.default_queue_name).enqueue,
        now=datetime.now(UTC),
    )


async def check_moodle(ctx: dict[str, Any]) -> None:
    redis = ctx["redis"]
    await poll_moodle(
        ctx["assembly"],
        LaunchQueue(redis, name=redis.default_queue_name).enqueue,
        now=datetime.now(UTC),
    )


async def _startup(ctx: dict[str, Any]) -> None:
    async with AsyncExitStack() as resources:
        ctx["assembly"] = await resources.enter_async_context(open_assembly())
        ctx["resources"] = resources.pop_all()


async def _shutdown(ctx: dict[str, Any]) -> None:
    await ctx["resources"].aclose()


class WorkerSettings:
    functions = [execute_manual]
    # Опрос Moodle — на полминуты позже расписаний, чтобы не ждать друг друга.
    cron_jobs = [cron(check_schedules, second=0), cron(check_moodle, second=30)]
    queue_name = QUEUE_NAME
    redis_settings = QueueSettings().connection_settings()
    job_serializer = staticmethod(serialize_job)
    job_deserializer = staticmethod(json.loads)
    on_startup = _startup
    on_shutdown = _shutdown
    max_jobs = 4  # Сборка держит до пяти соединений для блокировок.
    job_timeout = RUN_TIMEOUT + 30  # С запасом на запись статуса после тайм-аута.
    retry_jobs = False
    max_tries = 1
    keep_result = 0  # Результат и журнал живут в PostgreSQL.
    job_completion_wait = 15
