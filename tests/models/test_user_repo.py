"""Репозиторий людей: преподаватель находится по почте, учеников видит только их владелец."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.tables import GroupRow, GroupSource, Role, UserRow, group_members
from backend.models.users import UserRepository


def test_teacher_is_found_by_email_in_any_case(sessions):
    async def scenario():
        users = UserRepository(sessions)
        created = await users.create_teacher(name="Преподаватель А", email=" A@Example.test ")

        found = await users.find_by_email("a@EXAMPLE.test")
        assert found is not None
        assert (found.id, found.role, found.email) == (created.id, Role.TEACHER, "a@example.test")
        assert found.created_at is not None
        assert (await users.get(created.id)).name == "Преподаватель А"

    asyncio.run(scenario())


def test_unknown_user_is_none(sessions):
    async def scenario():
        users = UserRepository(sessions)
        assert await users.get(uuid.uuid4()) is None
        assert await users.find_by_email("nobody@example.test") is None

    asyncio.run(scenario())


def test_second_user_with_same_email_is_rejected(sessions, teacher):
    async def scenario():
        with pytest.raises(IntegrityError):
            await UserRepository(sessions).create_teacher(name="Двойник", email="A@example.test")

    asyncio.run(scenario())


def test_teacher_sees_only_own_students(sessions, teacher, other_teacher):
    async def scenario():
        users = UserRepository(sessions)
        first = await users.create_student(teacher.id, name="Ученик 1")
        second = await users.create_student(teacher.id, name="Ученик 2")
        await users.create_student(other_teacher.id, name="Ученик 3")

        own = await users.list_students(teacher.id)
        assert {student.id for student in own} == {first.id, second.id}
        assert [student.name for student in await users.list_students(other_teacher.id)] == [
            "Ученик 3"
        ]

    asyncio.run(scenario())


def test_student_needs_only_a_name(sessions, teacher):
    """Об ученике хранится минимум: почты, пароля и Telegram может не быть."""

    async def scenario():
        student = await UserRepository(sessions).create_student(teacher.id, name="Лис")
        assert (student.role, student.owner_id) == (Role.STUDENT, teacher.id)
        assert (student.email, student.password_hash, student.telegram_id) == (None, None, None)
        assert student.external_ids == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("role", [Role.ADMIN, Role.TEACHER])
def test_every_staff_role_is_stored(sessions, role):
    """Допустимые роли проверяет сама база; новая роль требует миграции."""

    async def scenario():
        users = UserRepository(sessions)
        created = await users.create_teacher(
            name="Сотрудник", email="staff@example.test", role=role
        )
        assert (await users.get(created.id)).role == role

    asyncio.run(scenario())


@pytest.mark.parametrize("source", list(GroupSource))
def test_group_of_every_source_keeps_its_students(sessions, teacher, source):
    async def scenario():
        student = await UserRepository(sessions).create_student(teacher.id, name="Ученик 1")
        group = GroupRow(owner_id=teacher.id, name="11 класс", source=source)
        async with sessions.begin() as session:
            session.add(group)
            await session.flush()
            await session.execute(
                group_members.insert().values(group_id=group.id, student_id=student.id)
            )
        async with sessions() as session:
            members = await session.scalars(
                select(group_members.c.student_id).where(group_members.c.group_id == group.id)
            )
            assert list(members) == [student.id]
            assert (await session.get(GroupRow, group.id)).source == source

    asyncio.run(scenario())


def test_group_from_unknown_source_is_rejected(sessions, teacher):
    async def scenario():
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(GroupRow(owner_id=teacher.id, name="Кружок", source="google"))

    asyncio.run(scenario())


def test_student_without_teacher_is_rejected(sessions):
    async def scenario():
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(UserRow(role=Role.STUDENT, name="Ничей"))

    asyncio.run(scenario())


def test_unknown_role_is_rejected(sessions):
    async def scenario():
        with pytest.raises(IntegrityError):
            async with sessions.begin() as session:
                session.add(UserRow(role="parent", name="Родитель"))

    asyncio.run(scenario())
