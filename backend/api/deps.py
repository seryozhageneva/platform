"""Что эндпоинт получает готовым: сборку и того, кто спрашивает.

Входа по почте и паролю ещё нет (задача 13). До тех пор запрос сам называет преподавателя
в заголовке `X-Teacher-Id`, а сервер проверяет только, что такой преподаватель есть. Это
годится, пока сервер слушает один этот компьютер (ADR 0013). Настоящий вход заменит
функцию `current_teacher` — эндпоинты при этом не меняются.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, Request

from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut
from backend.models.tables import Role, UserRow
from backend.triggers.assembly import Assembly

# Ответы-отказы, общие для всех эндпоинтов, — чтобы они попали в описание OpenAPI.
REFUSALS = {
    401: {"model": ErrorOut, "description": "Не сказано, кто спрашивает"},
    404: {"model": ErrorOut, "description": "Не найдено среди своих записей"},
    422: {"model": ErrorOut, "description": "Запрос не принят: причины — в `problems`"},
}


def get_assembly(request: Request) -> Assembly:
    return request.app.state.assembly


Assembled = Annotated[Assembly, Depends(get_assembly)]


async def current_teacher(
    assembly: Assembled,
    x_teacher_id: Annotated[
        str | None, Header(description="Идентификатор преподавателя (временно, до задачи 13)")
    ] = None,
) -> UserRow:
    try:
        user_id = uuid.UUID(x_teacher_id or "")
    except ValueError:
        raise ApiError(401, "в заголовке X-Teacher-Id нужен идентификатор преподавателя") from None
    user = await assembly.users.get(user_id)
    if user is None or user.role not in (Role.TEACHER, Role.ADMIN):
        raise ApiError(401, "преподаватель не найден")
    return user


Teacher = Annotated[UserRow, Depends(current_teacher)]
