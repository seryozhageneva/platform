"""Сборка, сеанс и роль пользователя для обработчиков API."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie

from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut
from backend.models.tables import Role, UserRow
from backend.triggers.assembly import Assembly

# Ответы-отказы, общие для всех эндпоинтов, — чтобы они попали в описание OpenAPI.
REFUSALS = {
    401: {"model": ErrorOut, "description": "Не сказано, кто спрашивает"},
    403: {"model": ErrorOut, "description": "Действие недоступно"},
    404: {"model": ErrorOut, "description": "Не найдено среди своих записей"},
    409: {"model": ErrorOut, "description": "Сеанс сменился"},
    422: {"model": ErrorOut, "description": "Запрос не принят: причины — в `problems`"},
}


def get_assembly(request: Request) -> Assembly:
    return request.app.state.assembly


Assembled = Annotated[Assembly, Depends(get_assembly)]


SESSION_COOKIE = "platform_session"
SessionToken = Annotated[str | None, Depends(APIKeyCookie(name=SESSION_COOKIE, auto_error=False))]


def same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.getlist("origin") != [expected]:
        raise ApiError(403, "запрос должен быть отправлен с сайта платформы")


async def current_user(assembly: Assembled, token: SessionToken) -> UserRow:
    user = await assembly.auth.current(token) if token else None
    if user is None:
        raise ApiError(401, "войдите в платформу")
    return user


CurrentUser = Annotated[UserRow, Depends(current_user)]


async def current_teacher(
    user: CurrentUser,
    expected_account: Annotated[UUID | None, Header(alias="X-Expected-Account")] = None,
) -> UserRow:
    if user.role != Role.TEACHER:
        raise ApiError(403, "нужна учётная запись преподавателя")
    if expected_account is not None and user.id != expected_account:
        raise ApiError(409, "учётная запись сменилась, обновите кабинет")
    return user


Teacher = Annotated[UserRow, Depends(current_teacher)]
