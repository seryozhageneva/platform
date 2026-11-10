"""Одновременный вход по личной ссылке и её отзыв."""

import asyncio

from backend.models.auth import AuthRepository
from backend.models.users import UserRepository


def test_concurrent_login_does_not_survive_revocation(sessions, teacher):
    async def attempt():
        student = await UserRepository(sessions).create_student(teacher.id, name="Белка")
        auth = AuthRepository(sessions)
        issued = await auth.change_link(teacher.id, student.id, issue=True)
        assert isinstance(issued, tuple)
        link, _ = issued

        login, revoked = await asyncio.gather(
            auth.start_student(link),
            auth.change_link(teacher.id, student.id, issue=False),
        )

        assert revoked is not None
        if login is not None:
            assert await auth.current(login[1]) is None
        assert await auth.start_student(link) is None

    asyncio.run(attempt())
