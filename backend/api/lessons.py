"""Назначение урока преподавателем и прохождение урока учеником."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.api.deps import REFUSALS, Assembled, Student, Teacher
from backend.api.errors import ApiError
from backend.core.contracts.ports import AnswerForm
from backend.core.contracts.screens import AnswerFormData, AnswerFormResponse, ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.core.engine import ResponseRejected
from backend.models.assignments import LessonBusy
from backend.models.tables import AssignmentRow, Role
from backend.triggers.assembly import Assembly
from backend.triggers.manual import LaunchRefused, PipelineNotFound
from backend.triggers.responses import NotWaiting, answer_run
from backend.triggers.student import checked_lesson, open_lesson

router = APIRouter(tags=["Уроки"], responses=REFUSALS)
_BROWSER_FORMS = {AnswerForm.TEXT, AnswerForm.FORMULA}


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    pipeline_id: UUID
    params: dict[str, Any] = Field(default_factory=dict)


class AssignmentOut(BaseModel):
    id: UUID


class LessonSummary(AssignmentOut):
    name: str


class LessonScreen(AnswerFormData):
    forms: list[AnswerForm]
    node_id: str
    revision: str


class LessonOut(BaseModel):
    status: RunStatus
    screen: LessonScreen | None = None


class LessonResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    revision: str
    response: AnswerFormResponse


@router.post("/assignments", status_code=201, summary="Назначить урок ученику")
async def assign(body: AssignmentIn, teacher: Teacher, assembly: Assembled) -> AssignmentOut:
    student = await assembly.users.get(body.student_id)
    if student is None or student.role != Role.STUDENT or student.owner_id != teacher.id:
        raise ApiError(404, "ученик не найден")
    params = {name: value for name, value in body.params.items() if value is not None}
    try:
        await checked_lesson(assembly, teacher.id, body.pipeline_id, params)
    except PipelineNotFound as error:
        raise ApiError(404, str(error)) from None
    except LaunchRefused as error:
        raise ApiError(422, str(error), error.problems) from None
    row = await assembly.assignments.create(teacher.id, student.id, body.pipeline_id, params)
    return AssignmentOut(id=row.id)


@router.get("/student/lessons", summary="Список назначенных уроков")
async def list_lessons(student: Student, assembly: Assembled) -> list[LessonSummary]:
    return [
        LessonSummary(id=assignment_id, name=name)
        for assignment_id, name in await assembly.assignments.list_for(student.id)
    ]


@asynccontextmanager
async def _locked_lesson(
    assembly: Assembly, lesson_id: UUID, student_id: UUID
) -> AsyncIterator[AssignmentRow]:
    assignment = await assembly.assignments.get_for(lesson_id, student_id)
    if assignment is None:
        raise ApiError(404, "урок не найден")
    try:
        async with assembly.assignments.lock(lesson_id):
            yield assignment
    except LessonBusy:
        raise ApiError(409, "урок уже обновляется") from None


def _lesson_view(state: RunState, revision: str) -> LessonOut:
    if state.status is RunStatus.WAITING and state.waiting:
        waiting = state.waiting[0]
        if waiting.who == "student" and waiting.screen is ScreenType.ANSWER_FORM:
            data = AnswerFormData.model_validate(waiting.data)
            forms = [form for form in data.forms if form in _BROWSER_FORMS]
            if forms or data.can_ask_hint:
                screen = LessonScreen(
                    task_id=data.task_id,
                    statement=data.statement,
                    forms=forms,
                    hint=data.hint,
                    can_ask_hint=data.can_ask_hint,
                    node_id=waiting.node_id,
                    revision=revision,
                )
                return LessonOut(status=state.status, screen=screen)
    return LessonOut(status=state.status)


async def _saved_view(
    assembly: Assembly, lesson_id: UUID, student_id: UUID, state: RunState
) -> LessonOut:
    saved = await assembly.assignments.run_for(lesson_id, student_id)
    if saved is None:
        raise LookupError("запуск урока не сохранён")
    return _lesson_view(state, saved[1])


@router.post("/student/lessons/{lesson_id}/open", summary="Открыть или продолжить урок")
async def open_student_lesson(lesson_id: UUID, student: Student, assembly: Assembled) -> LessonOut:
    async with _locked_lesson(assembly, lesson_id, student.id) as assignment:
        run = await assembly.assignments.run_for(lesson_id, student.id)
        try:
            state = await open_lesson(assembly, assignment, student.id, run[0] if run else None)
        except PipelineNotFound as error:
            raise ApiError(404, str(error)) from None
        except LaunchRefused as error:
            raise ApiError(422, str(error), error.problems) from None
        return await _saved_view(assembly, lesson_id, student.id, state)


@router.post("/student/lessons/{lesson_id}/responses", summary="Ответить или попросить подсказку")
async def respond_to_lesson(
    lesson_id: UUID, body: LessonResponseIn, student: Student, assembly: Assembled
) -> LessonOut:
    async with _locked_lesson(assembly, lesson_id, student.id):
        run = await assembly.assignments.run_for(lesson_id, student.id)
        if run is None or run[1] != body.revision:
            raise ApiError(409, "экран урока изменился, откройте его снова")
        state = await assembly.runs.load(str(run[0]))
        if state is None:
            raise LookupError("запуск урока исчез")
        screen = _lesson_view(state, run[1]).screen
        if screen is None or screen.node_id != body.node_id:
            raise ApiError(409, "урок не ждёт ответа на этом экране")
        response = body.response
        if response.action == "hint":
            if not screen.can_ask_hint or response.answer is not None:
                raise ApiError(422, "на этом экране нельзя запросить подсказку таким способом")
        else:
            answer = response.answer
            assert answer is not None
            if (
                answer.task_id != screen.task_id
                or answer.form not in screen.forms
                or not (answer.text or "").strip()
                or answer.file is not None
            ):
                raise ApiError(422, "ответ не подходит к этой задаче")
        try:
            state = await answer_run(
                assembly, state, body.node_id, response.model_dump(mode="json")
            )
        except NotWaiting as error:
            raise ApiError(409, str(error)) from None
        except ResponseRejected as error:
            raise ApiError(422, str(error)) from None
        return await _saved_view(assembly, lesson_id, student.id, state)
