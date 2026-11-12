"""Подключения преподавателя к Moodle, Telegram и облаку (ADR 0028, 0033, 0036).

Токен принимается, шифруется и больше никогда не отдаётся: в ответах только вид, адрес и
время изменения. Чужие подключения не видны. Формы в браузере пока нет — только API.
"""

import re
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

TELEGRAM_API = "https://api.telegram.org"
_BOT_TOKEN = re.compile(r"[0-9]{1,20}:[A-Za-z0-9_-]+")
# Облако — Яндекс Диск; токен OAuth из букв, цифр, «_», «-» и «.».
CLOUD_API = "https://cloud-api.yandex.net"
_OAUTH_TOKEN = re.compile(r"[A-Za-z0-9_.-]{16,}")


class ConnectionIn(BaseModel):
    url: Annotated[
        str | None,
        Field(description="Адрес сайта Moodle. Для Telegram и облака можно опустить."),
    ] = None
    # SecretStr: токен не попадёт в журнал и в текст ошибок проверки.
    token: Annotated[
        SecretStr, Field(description="Токен Moodle, бота или Яндекс Диска; не возвращается")
    ]

    @field_validator("url")
    @classmethod
    def _site_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
        if not secret or len(secret) > 256:
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
    url, token = connection.url, connection.token.get_secret_value()
    if kind is ConnectionKind.TELEGRAM:
        if url not in (None, TELEGRAM_API):
            raise ApiError(422, "для Telegram используется только https://api.telegram.org")
        if not _BOT_TOKEN.fullmatch(token):
            raise ApiError(422, "токен бота Telegram записан в неверном формате")
        url = TELEGRAM_API
    elif kind is ConnectionKind.CLOUD:
        if url not in (None, CLOUD_API):
            raise ApiError(422, "для облака используется только Яндекс Диск: " + CLOUD_API)
        if not _OAUTH_TOKEN.fullmatch(token):
            raise ApiError(422, "токен Яндекс Диска записан в неверном формате")
        url = CLOUD_API
    elif url is None or not token.isalnum():
        raise ApiError(422, "для Moodle нужны адрес сайта и буквенно-цифровой токен")
    row = await _repository(assembly).save(teacher.id, kind, url=url, token=token)
    return ConnectionOut.of(row)


@router.delete("/{kind}", status_code=204, summary="Удалить подключение")
async def delete_connection(
    kind: ConnectionKind, teacher: Teacher, assembly: Assembled
) -> Response:
    if not await _repository(assembly).delete(teacher.id, kind):
        raise ApiError(404, "подключение не найдено")
    return Response(status_code=204)
