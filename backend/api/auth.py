"""Вход преподавателя и ученика через браузер."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from starlette.concurrency import run_in_threadpool

from backend.api.deps import REFUSALS, SESSION_COOKIE, Assembled, CurrentUser, SessionToken
from backend.api.errors import ApiError
from backend.api.passwords import verify_password
from backend.models.tables import Role

router = APIRouter(prefix="/auth", tags=["Вход"], responses=REFUSALS)


def _require_utf8[T: (str, SecretStr)](value: T) -> T:
    text = value.get_secret_value() if isinstance(value, SecretStr) else value
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("ожидается текст в UTF-8") from None
    return value


class TeacherLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=254),
        AfterValidator(_require_utf8),
    ]
    password: Annotated[
        SecretStr, Field(min_length=1, max_length=1024), AfterValidator(_require_utf8)
    ]


class StudentLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[SecretStr, Field(min_length=1, max_length=128), AfterValidator(_require_utf8)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: Literal["teacher", "student"]


def _set_session(request: Request, response: Response, token: str, expiry: datetime) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(0, int((expiry - datetime.now(UTC)).total_seconds())),
        expires=expiry,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/api/v1",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/teacher")
async def login_teacher(
    body: TeacherLogin, request: Request, response: Response, assembly: Assembled
) -> UserOut:
    user = await assembly.users.find_by_email(body.email)
    stored = user.password_hash if user is not None and user.role == Role.TEACHER else None
    valid = await run_in_threadpool(verify_password, stored, body.password.get_secret_value())
    if user is None or not valid:
        raise ApiError(401, "неверная почта или пароль")
    token, expiry = await assembly.auth.start_teacher(user.id)
    _set_session(request, response, token, expiry)
    return UserOut.model_validate(user)


@router.post("/student")
async def login_student(
    body: StudentLogin, request: Request, response: Response, assembly: Assembled
) -> UserOut:
    login = await assembly.auth.start_student(body.token.get_secret_value())
    if login is None:
        raise ApiError(401, "ссылка недействительна или истекла")
    student, token, expiry = login
    _set_session(request, response, token, expiry)
    return UserOut.model_validate(student)


@router.get("/me")
async def read_me(user: CurrentUser, response: Response) -> UserOut:
    response.headers["Cache-Control"] = "no-store"
    return UserOut.model_validate(user)


@router.post("/logout", status_code=204)
async def logout(assembly: Assembled, token: SessionToken, request: Request) -> Response:
    if token:
        await assembly.auth.end(token)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api/v1",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response
