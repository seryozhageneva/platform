"""Эндпоинты запусков: запустить вручную, посмотреть состояние и журнал событий.

Запрос на запуск отвечает, когда запуск закончился, встал на паузу или остановился с
ошибкой: движок выполняется прямо в запросе (ADR 0013).
"""

import uuid

from fastapi import APIRouter

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import EventOut, LaunchRequest, RunOut
from backend.core.contracts.state import RunState
from backend.models.tables import UserRow
from backend.triggers.assembly import Assembly
from backend.triggers.manual import LaunchRefused, start_manual

router = APIRouter(tags=["Запуски"], responses=REFUSALS)


@router.post("/pipelines/{pipeline_id}/runs", status_code=201, summary="Запустить пайплайн вручную")
async def launch_manually(
    pipeline_id: uuid.UUID, teacher: Teacher, assembly: Assembled, body: LaunchRequest | None = None
) -> RunOut:
    try:
        state = await start_manual(
            assembly,
            teacher_id=teacher.id,
            pipeline_id=pipeline_id,
            params=body.params if body else {},
        )
    except LookupError as error:
        raise ApiError(404, str(error)) from None
    except LaunchRefused as refused:
        raise ApiError(422, str(refused), refused.problems) from None
    return RunOut.of(state)


async def _own_run(assembly: Assembly, teacher: UserRow, run_id: uuid.UUID) -> RunState:
    """Запуск этого преподавателя; чужой запуск для него всё равно что несуществующий."""
    state = await assembly.runs.load(str(run_id))
    if state is None or state.teacher_id != str(teacher.id):
        raise ApiError(404, "запуск не найден")
    return state


@router.get("/runs/{run_id}", summary="Состояние запуска")
async def get_run(run_id: uuid.UUID, teacher: Teacher, assembly: Assembled) -> RunOut:
    return RunOut.of(await _own_run(assembly, teacher, run_id))


@router.get("/runs/{run_id}/events", summary="Журнал событий запуска")
async def get_run_events(
    run_id: uuid.UUID, teacher: Teacher, assembly: Assembled
) -> list[EventOut]:
    await _own_run(assembly, teacher, run_id)
    return [EventOut.of(row) for row in await assembly.runs.events(str(run_id))]
