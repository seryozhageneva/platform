"""Преподаватель управляет учениками и их личными ссылками."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError

router = APIRouter(prefix="/students", tags=["Ученики"], responses=REFUSALS)


class StudentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    link_expires_at: datetime | None


class StudentLinkOut(BaseModel):
    token: str
    expires_at: datetime


@router.get("")
async def list_students(assembly: Assembled, teacher: Teacher) -> list[StudentOut]:
    return [
        StudentOut.model_validate(row) for row in await assembly.users.list_students(teacher.id)
    ]


@router.post("", status_code=201)
async def create_student(body: StudentCreate, assembly: Assembled, teacher: Teacher) -> StudentOut:
    return StudentOut.model_validate(
        await assembly.users.create_student(teacher.id, name=body.name)
    )


@router.post("/{student_id}/link")
async def issue_link(
    student_id: UUID, assembly: Assembled, teacher: Teacher, response: Response
) -> StudentLinkOut:
    result = await assembly.auth.change_link(teacher.id, student_id, issue=True)
    if not isinstance(result, tuple):
        raise ApiError(404, "ученик не найден")
    token, expiry = result
    response.headers["Cache-Control"] = "no-store"
    return StudentLinkOut(token=token, expires_at=expiry)


@router.delete("/{student_id}/link", status_code=204)
async def revoke_link(student_id: UUID, assembly: Assembled, teacher: Teacher) -> Response:
    if await assembly.auth.change_link(teacher.id, student_id, issue=False) is None:
        raise ApiError(404, "ученик не найден")
    return Response(status_code=204)
