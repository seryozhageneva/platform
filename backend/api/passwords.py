"""Хэширование и проверка паролей вне цикла обработки HTTP-запросов."""

from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("заглушка проверки неизвестной почты")


def verify_password(stored: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored or _dummy_hash(), password) and bool(stored)
    except (VerificationError, InvalidHashError):
        return False
