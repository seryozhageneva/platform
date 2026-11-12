"""Триггер «событие Moodle»: опрос Moodle и запуск на новые сдачи (ADR 0034).

Вебхуков нет (решение 7 в docs/vision.md): рабочий процесс раз в минуту смотрит включённые
наблюдения и опрашивает Moodle тех, у кого подошёл срок `poll_minutes`. Лёгкий инструмент
`list_submissions` даёт номера сданных работ без файлов. Если среди них есть новые — ещё не
взятые этим пайплайном или изменённые после сдачи, — создаётся один запуск на все новые.
Номера сдач едут в `payload` события, и блок «Источник: работы из Moodle» скачивает только
их. Сдачи отмечаются обработанными в одной транзакции с запуском.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from backend.core.contracts.pipeline import Pipeline
from backend.core.contracts.ports import Event, TriggerType
from backend.core.data_flow import with_params
from backend.models.run_store import MoodleWatchChanged
from backend.models.tables import MoodleWatchRow, PipelineRow
from backend.triggers.assembly import Assembly
from backend.triggers.manual import launch_problems
from backend.triggers.moodle_graph import moodle_launch, moodle_source, poll_minutes
from backend.triggers.queue import EnqueueLaunch, QueueUnavailable

logger = logging.getLogger(__name__)


def _course_and_assignment(pipeline: Pipeline, params: Mapping[str, Any]) -> tuple[int, int]:
    values = {param.name: params.get(param.name, param.default) for param in pipeline.params}
    config = with_params(moodle_source(pipeline).config, values)
    return config["course_id"], config["assignment_id"]


def _marks(answer: Any) -> list[tuple[int, int]]:
    """Номера и время сдач из ответа сервера; платформа ему не доверяет и проверяет поля."""
    items = answer.get("submissions") if isinstance(answer, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("MCP-сервер Moodle прислал список сдач в неверном формате")
    marks: list[tuple[int, int]] = []
    for item in items:
        number = item.get("submission_id") if isinstance(item, dict) else None
        at = item.get("submitted_at") if isinstance(item, dict) else None
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (number, at)):
            raise RuntimeError("MCP-сервер Moodle прислал список сдач в неверном формате")
        if (number, at) not in marks:
            marks.append((number, at))
    return marks


async def poll_moodle(assembly: Assembly, enqueue: EnqueueLaunch, *, now: datetime) -> None:
    """Опрашивает Moodle по всем включённым наблюдениям, у которых подошёл срок."""
    minute = now.astimezone(UTC).replace(second=0, microsecond=0)
    for watch, row in await assembly.moodle_watches.enabled():
        try:
            await _poll_one(assembly, enqueue, watch, row, minute)
        except Exception as error:
            # Один сломанный пайплайн не мешает опросу остальных. Текст не печатаем: в нём
            # может быть ответ внешней системы.
            logger.error("Опрос Moodle для пайплайна %s: %s", row.id, type(error).__name__)


async def _poll_one(
    assembly: Assembly,
    enqueue: EnqueueLaunch,
    watch: MoodleWatchRow,
    row: PipelineRow,
    minute: datetime,
) -> None:
    pipeline = await assembly.pipelines.load(row.id, row.latest_version)
    launch = None if pipeline is None else moodle_launch(pipeline)
    minutes = None if launch is None else poll_minutes(launch)
    if pipeline is None or minutes is None:
        return
    if (
        watch.last_polled_at is not None
        and watch.last_polled_at + timedelta(minutes=minutes) > minute
    ):
        return
    problems = launch_problems(assembly, pipeline, TriggerType.MOODLE_EVENT, watch.params)
    if problems:
        if await assembly.moodle_watches.claim_poll(watch, minute):
            await assembly.moodle_watches.record_error(row.id, problems[0].message)
        return
    if not await assembly.moodle_watches.claim_poll(watch, minute):
        return
    course_id, assignment_id = _course_and_assignment(pipeline, watch.params)
    try:
        if assembly.moodle_tools is None:
            raise RuntimeError("подключения недоступны: в настройках платформы нет ключа")
        tools = await assembly.moodle_tools(row.owner_id, "moodle")
        answer = await tools.call_tool(
            "moodle",
            "list_submissions",
            {"course_id": course_id, "assignment_id": assignment_id},
            read_only=True,
        )
        fresh = await assembly.moodle_watches.unseen(row.id, _marks(answer))
    except RuntimeError as error:
        # Текст ошибки MCP-клиента и сервера можно показать преподавателю: токена в нём нет.
        await assembly.moodle_watches.record_error(row.id, str(error))
        return
    if fresh:
        target = (course_id, assignment_id)
        await _launch(assembly, enqueue, pipeline, watch, row, minute, fresh, target)
    await assembly.moodle_watches.record_error(row.id, None)


async def _launch(
    assembly: Assembly,
    enqueue: EnqueueLaunch,
    pipeline: Pipeline,
    watch: MoodleWatchRow,
    row: PipelineRow,
    minute: datetime,
    fresh: list[tuple[int, int]],
    target: tuple[int, int],
) -> None:
    course_id, assignment_id = target
    event = Event(
        trigger=TriggerType.MOODLE_EVENT,
        occurred_at=minute,
        payload={
            "moodle_course_id": course_id,
            "moodle_assignment_id": assignment_id,
            "moodle_submission_ids": [number for number, _ in fresh],
        },
    )
    state = assembly.engine().prepare(
        pipeline,
        run_id=str(uuid4()),
        pipeline_id=str(row.id),
        pipeline_version=row.latest_version,
        event=event,
        params=watch.params,
        teacher_id=str(row.owner_id),
    )
    try:
        async with assembly.runs.queue_launch(
            state,
            pipeline.trigger().id,
            moodle_marks=fresh,
            moodle_params=watch.params,
        ):
            await enqueue(UUID(state.run_id))
    except MoodleWatchChanged:
        return
    except QueueUnavailable:
        # Сдачи не отмечены: следующий опрос возьмёт их снова.
        logger.warning("Очередь не приняла запуск пайплайна %s по событию Moodle", row.id)
