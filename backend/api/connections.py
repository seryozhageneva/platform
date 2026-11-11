"""Подключения преподавателя к внешним системам (ADR 0028): пока только Moodle.

Токен принимается, шифруется и больше никогда не отдаётся: в ответах только вид, адрес и
время изменения. Чужие подключения не видны. Формы в браузере пока нет — только API.
"""

from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, SecretStr, field_validator

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut
from backend.models.connections import ConnectionRepository
from backend.models.tables import ConnectionKind, ConnectionRow

router = APIRouter(
    prefix="/connections",
    tags=["Подключения"],
    responses=REFUSALS | {503: {"model": ErrorOut, "description": "Не задан ключ шифрования"}},
)


class ConnectionIn(BaseModel):
    url: Annotated[str, Field(description="Адрес сайта, например https://moodle.example.ru")]
    # SecretStr: токен не попадёт в журнал и в текст ошибок проверки.
    token: Annotated[SecretStr, Field(description="Токен веб-сервиса; в ответах не возвращается")]

    @field_validator("url")
    @classmethod
    def _site_address(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("адрес сайта записан с ошибкой") from None
        if url.scheme not in ("http", "https") or not url.host or url.query or url.fragment:
            raise ValueError("нужен адрес сайта вида https://moodle.example.ru")
        if url.userinfo:
            raise ValueError("логин и пароль в адресе не нужны: доступ даёт токен")
        return value

    @field_validator("token")
    @classmethod
    def _token(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value().strip()
        if not secret or len(secret) > 256 or not secret.isalnum():
            raise ValueError("токен пуст или похож не на токен")
        return SecretStr(secret)


class ConnectionOut(BaseModel):
    kind: ConnectionKind
    url: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: ConnectionRow) -> "ConnectionOut":
        return cls(
            kind=ConnectionKind(row.kind),
            url=row.url,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _repository(assembly: Assembled) -> ConnectionRepository:
    if assembly.connections is None:
        raise ApiError(
            503, "подключения недоступны: в .env сервера не задан ключ PLATFORM_SECRET_KEY"
        )
    return assembly.connections


@router.get("", summary="Свои подключения")
async def list_connections(teacher: Teacher, assembly: Assembled) -> list[ConnectionOut]:
    rows = await _repository(assembly).list(teacher.id)
    return [ConnectionOut.of(row) for row in rows]


@router.put("/{kind}", summary="Создать или заменить подключение")
async def save_connection(
    kind: ConnectionKind, connection: ConnectionIn, teacher: Teacher, assembly: Assembled
) -> ConnectionOut:
    row = await _repository(assembly).save(
        teacher.id, kind, url=connection.url, token=connection.token.get_secret_value()
    )
    return ConnectionOut.of(row)


@router.delete("/{kind}", status_code=204, summary="Удалить подключение")
async def delete_connection(
    kind: ConnectionKind, teacher: Teacher, assembly: Assembled
) -> Response:
    if not await _repository(assembly).delete(teacher.id, kind):
        raise ApiError(404, "подключение не найдено")
    return Response(status_code=204)
