"""Эндпоинты банка задач: создать, найти, прочитать, исправить (ADR 0015).

Банк у каждого преподавателя свой: чужая задача выглядит так же, как несуществующая.
Задачи для урока из банка берёт блок «Источник: банк задач» — через хранилище платформы.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import TaskIn, TaskOut
from backend.models.tables import TaskStatus

router = APIRouter(prefix="/tasks", tags=["Банк задач"], responses=REFUSALS)


@router.post("", status_code=201, summary="Добавить задачу в банк")
async def create_task(task: TaskIn, teacher: Teacher, assembly: Assembled) -> TaskOut:
    row = await assembly.tasks.create(teacher.id, **task.model_dump())
    return TaskOut.of(row)


@router.get("", summary="Свои задачи; незаданное условие не учитывается")
async def find_tasks(
    teacher: Teacher,
    assembly: Assembled,
    subject: str | None = None,
    topic: str | None = None,
    difficulty: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[
        TaskStatus | None, Query(description="Без статуса — и черновики, и подтверждённые")
    ] = None,
) -> list[TaskOut]:
    rows = await assembly.tasks.find(
        teacher.id,
        subject=subject.strip() if subject is not None else None,
        topic=topic.strip() if topic is not None else None,
        difficulty=difficulty,
        status=status,
    )
    return [TaskOut.of(row) for row in rows]


@router.get("/{task_id}", summary="Одна своя задача")
async def get_task(task_id: uuid.UUID, teacher: Teacher, assembly: Assembled) -> TaskOut:
    row = await assembly.tasks.get(teacher.id, task_id)
    if row is None:
        raise ApiError(404, "задача не найдена")
    return TaskOut.of(row)


@router.put("/{task_id}", summary="Исправить задачу или подтвердить черновик")
async def update_task(
    task_id: uuid.UUID, task: TaskIn, teacher: Teacher, assembly: Assembled
) -> TaskOut:
    row = await assembly.tasks.update(teacher.id, task_id, **task.model_dump())
    if row is None:
        raise ApiError(404, "задача не найдена")
    return TaskOut.of(row)
