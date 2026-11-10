"""Эндпоинты запусков: запустить вручную, ответить на паузе, посмотреть состояние и журнал.

Запрос на запуск и ответ отвечают, когда запуск закончился, встал на паузу или остановился
с ошибкой: движок выполняется прямо в запросе (ADR 0013). Преподаватель отвечает
на паузе ручного запуска (ADR 0016) и подтверждает таблицу в назначенном уроке.
"""

import uuid

from fastapi import APIRouter
from pydantic import ValidationError

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut, EventOut, LaunchRequest, ResponseIn, RunOut, RunSummary
from backend.core.contracts.screens import ReviewTableResponse, ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.core.engine import ResponseRejected
from backend.models.assignments import LessonBusy, LessonLockUnavailable
from backend.models.tables import UserRow
from backend.triggers.assembly import Assembly
from backend.triggers.manual import LaunchRefused, PipelineNotFound, start_manual
from backend.triggers.responses import NotWaiting, answer_run

router = APIRouter(tags=["Запуски"], responses=REFUSALS)


@router.get("/runs", summary="Свои запуски")
async def list_runs(teacher: Teacher, assembly: Assembled) -> list[RunSummary]:
    return [RunSummary.model_validate(row) for row in await assembly.runs.for_teacher(teacher.id)]


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
            expected_version=body.expected_version if body else None,
        )
    except PipelineNotFound as error:
        raise ApiError(404, str(error)) from None
    except LaunchRefused as refused:
        raise ApiError(422, str(refused), refused.problems) from None
    return await _run_view(assembly, teacher, uuid.UUID(state.run_id))


async def _own_run(
    assembly: Assembly, teacher: UserRow, run_id: uuid.UUID
) -> tuple[RunState, uuid.UUID | None]:
    """Запуск этого преподавателя; чужой запуск для него всё равно что несуществующий."""
    result = await assembly.runs.load_with_approval(run_id)
    if result is None or result[0].teacher_id != str(teacher.id):
        raise ApiError(404, "запуск не найден")
    return result


async def _run_view(assembly: Assembly, teacher: UserRow, run_id: uuid.UUID) -> RunOut:
    state, approval_id = await _own_run(assembly, teacher, run_id)
    return RunOut.of(state, approval_id if state.status is RunStatus.WAITING else None)


@router.get("/runs/{run_id}", summary="Состояние запуска")
async def get_run(run_id: uuid.UUID, teacher: Teacher, assembly: Assembled) -> RunOut:
    return await _run_view(assembly, teacher, run_id)


@router.get("/runs/{run_id}/events", summary="Журнал событий запуска")
async def get_run_events(
    run_id: uuid.UUID, teacher: Teacher, assembly: Assembled
) -> list[EventOut]:
    await _own_run(assembly, teacher, run_id)
    return [EventOut.of(row) for row in await assembly.runs.events(str(run_id))]


@router.post(
    "/runs/{run_id}/responses",
    summary="Ответить запуску, который ждёт человека",
    responses={
        409: {"model": ErrorOut, "description": "Пауза изменилась или запуск уже обновляется"},
        503: {"model": ErrorOut, "description": "Сервер запусков занят"},
    },
)
async def respond(
    run_id: uuid.UUID, body: ResponseIn, teacher: Teacher, assembly: Assembled
) -> RunOut:
    await _own_run(assembly, teacher, run_id)
    assignment_id = await assembly.assignments.assignment_for_run(run_id)
    try:
        # Для назначенного урока это та же блокировка, что у запросов ученика.
        async with assembly.assignments.lock(assignment_id or run_id):
            state, approval_id = await _own_run(assembly, teacher, run_id)
            waiting = next((item for item in state.waiting if item.node_id == body.node_id), None)
            if body.approval_id is not None and (
                state.status is not RunStatus.WAITING
                or waiting is None
                or waiting.screen is not ScreenType.REVIEW_TABLE
                or body.approval_id != approval_id
            ):
                raise ApiError(409, "эта таблица больше не ждёт решения")
            if assignment_id is not None and (waiting is None or waiting.who != "teacher"):
                raise ApiError(403, "на назначенный урок отвечает ученик")
            decision = None
            if (
                state.status is RunStatus.WAITING
                and waiting is not None
                and waiting.screen is ScreenType.REVIEW_TABLE
            ):
                if approval_id is None or body.approval_id != approval_id:
                    raise ApiError(409, "обновите таблицу перед отправкой решения")
                try:
                    response = ReviewTableResponse.model_validate(body.response)
                except ValidationError:
                    raise ApiError(422, "ответ не подходит таблице подтверждения") from None
                outcome = "approved" if any(row.keep for row in response.rows) else "rejected"
                decision = (approval_id, outcome, response.model_dump(mode="json"))
            await answer_run(
                assembly,
                state,
                body.node_id,
                body.response,
                assignment_id=assignment_id,
                approval=decision,
            )
            return await _run_view(assembly, teacher, run_id)
    except NotWaiting as error:
        raise ApiError(409, str(error)) from None
    except LessonBusy:
        raise ApiError(409, "запуск уже обновляется") from None
    except LessonLockUnavailable:
        raise ApiError(503, "сервер запусков занят, попробуйте ещё раз") from None
    except ResponseRejected as error:
        raise ApiError(422, str(error)) from None
