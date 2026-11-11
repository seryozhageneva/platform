"""Результаты кабинета: что блоки-получатели записали преподавателю и ученику (ADR 0027)."""

from fastapi import APIRouter

from backend.api.deps import REFUSALS, Assembled, Student, Teacher
from backend.api.schemas import CabinetResultOut, StudentResultOut

router = APIRouter(tags=["Результаты"], responses=REFUSALS)


@router.get("/results", summary="Результаты в кабинете преподавателя, новые первыми")
async def list_teacher_results(teacher: Teacher, assembly: Assembled) -> list[CabinetResultOut]:
    return [
        CabinetResultOut(
            id=result.id,
            run_id=result.run_id,
            title=result.title,
            content=result.content,
            student_id=result.student_id,
            student_name=result.student_name,
            created_at=result.created_at,
        )
        for result in await assembly.results.list_for_teacher(teacher.id)
    ]


@router.get("/student/results", summary="Результаты, адресованные ученику, новые первыми")
async def list_student_results(student: Student, assembly: Assembled) -> list[StudentResultOut]:
    return [
        StudentResultOut(
            id=result.id, title=result.title, content=result.content, created_at=result.created_at
        )
        for result in await assembly.results.list_for_student(student.id)
    ]
