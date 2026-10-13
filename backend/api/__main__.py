"""Запуск сервера API на своём компьютере:  uv run python -m backend.api

Сервер слушает только этот компьютер (127.0.0.1): входа ещё нет (задача 13), и из сети он
быть виден не должен. Страница с описанием API — http://127.0.0.1:8000/docs
"""

import asyncio
import sys

import uvicorn

from backend.api.app import create_app
from backend.llm.factory import make_llm
from backend.llm.providers import LLMError
from backend.models.db import database_url

HOST, PORT = "127.0.0.1", 8000


def main() -> int:
    # Настройки проверяются до старта: понятная строка лучше, чем отчёт об ошибке сервера.
    try:
        database_url()
        asyncio.run(make_llm().aclose())
    except (RuntimeError, LLMError) as error:
        print(f"Сервер не запущен: {error}")
        return 1
    uvicorn.run(create_app(), host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
