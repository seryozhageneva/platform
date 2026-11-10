"""Локальный сервер для выдуманного урока с дробью и фейковой моделью."""

import asyncio

import uvicorn

from backend.api.__main__ import HOST, PORT
from backend.api.app import create_app
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.db import make_engine, make_sessions
from backend.triggers.assembly import Assembly

HINT = "На какое число делятся и числитель, и знаменатель?"


async def main() -> None:
    engine = make_engine()
    try:
        # Один запрос подсказки в демонстрации: сначала текст, затем решение контролёра.
        llm = FakeLLM([HINT, {"approved": True}])
        assembly = Assembly(make_sessions(engine), load_registry(BUILTIN_BLOCKS), llm)
        server = uvicorn.Server(uvicorn.Config(create_app(assembly), host=HOST, port=PORT))
        await server.serve()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
