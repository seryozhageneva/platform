"""Загрузка документов преподавателем (ADR 0023) и скачивание своих файлов (ADR 0027)."""

import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut
from backend.core.contracts.ports import FileKind, FileRef
from backend.models.files import as_contract
from backend.models.tables import Role

router = APIRouter(prefix="/files", tags=["Файлы"], responses=REFUSALS)

MAX_FILE_SIZE = 10 * 1024 * 1024
DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post(
    "",
    status_code=201,
    summary="Загрузить PDF или DOCX",
    responses={
        413: {"model": ErrorOut, "description": "Файл больше 10 МиБ"},
        415: {"model": ErrorOut, "description": "Поддерживаются PDF и DOCX"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in sorted(DOCUMENT_TYPES)
            },
        },
    },
)
async def upload_file(
    request: Request,
    teacher: Teacher,
    assembly: Assembled,
    name: Annotated[str, Query(description="Имя файла")],
    student_id: UUID | None = None,
) -> FileRef:
    name = name.strip()
    if not name or "\x00" in name:
        raise ApiError(422, "укажите имя файла")

    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type not in DOCUMENT_TYPES:
        raise ApiError(415, "поддерживаются документы PDF и DOCX")

    if student_id is not None:
        student = await assembly.users.get(student_id)
        if student is None or student.role != Role.STUDENT or student.owner_id != teacher.id:
            raise ApiError(404, "ученик не найден")

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_FILE_SIZE:
            raise ApiError(413, "файл больше 10 МиБ")
        content.extend(chunk)
    if not content:
        raise ApiError(422, "файл пуст")

    row = await assembly.files.create(
        teacher.id,
        name=name,
        kind=FileKind.DOCUMENT,
        media_type=media_type,
        student_id=student_id,
        content=bytes(content),
    )
    return as_contract(row)


@router.get(
    "/{file_id}/content",
    summary="Скачать свой файл",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "Файл"}},
)
async def download_file(file_id: UUID, teacher: Teacher, assembly: Assembled) -> Response:
    row = await assembly.files.get(teacher.id, file_id)
    content = None if row is None else await assembly.files.read(teacher.id, file_id)
    if row is None or content is None:
        raise ApiError(404, "файл не найден")
    # Файл всегда скачивается, а не открывается на странице платформы: так файл любого типа
    # не сможет выполнить свой код от имени сайта. Для старых браузеров — имя латиницей.
    fallback = "file" + re.sub(r"[^A-Za-z0-9.]", "", Path(row.name).suffix)[:10]
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(row.name)}"
    return Response(
        content,
        media_type=row.media_type,
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )
