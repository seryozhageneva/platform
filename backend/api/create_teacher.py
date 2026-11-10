"""Создать преподавателя или задать первый пароль существующей записи."""

import argparse
import asyncio
import re
from getpass import getpass

from sqlalchemy.exc import IntegrityError

from backend.api.passwords import hash_password
from backend.models.auth import AuthRepository
from backend.models.db import make_engine, make_sessions
from backend.models.users import UserRepository

# Тот же набор символов, что принимает поле type="email" в браузере.
_EMAIL = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
)


async def _save(email: str, name: str | None, password: str) -> bool:
    engine = make_engine()
    try:
        sessions = make_sessions(engine)
        users = UserRepository(sessions)
        password_hash = hash_password(password)
        if name is None:
            user = await users.find_by_email(email)
            return user is not None and await AuthRepository(sessions).set_initial_password(
                user.id, password_hash
            )
        await users.create_teacher(name=name, email=email, password_hash=password_hash)
        return True
    except IntegrityError:
        return False
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--name", help="имя нового преподавателя")
    mode.add_argument("--set-initial-password", action="store_true")
    args = parser.parse_args()
    email = args.email.strip()
    name = args.name.strip() if args.name is not None else None
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        parser.error("укажите корректный адрес электронной почты")
    if name == "":
        parser.error("укажите имя преподавателя")
    password = getpass("Пароль: ")
    if not 12 <= len(password) <= 1024:
        parser.error("пароль должен содержать от 12 до 1024 символов")
    if password != getpass("Повторите пароль: "):
        parser.error("пароли не совпадают")
    if not asyncio.run(_save(email, name, password)):
        parser.error("запись уже существует или не подходит для установки первого пароля")
    print("Учётная запись готова к входу.")


if __name__ == "__main__":
    main()
