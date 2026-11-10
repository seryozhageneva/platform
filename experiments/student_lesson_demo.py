"""Локальный сервер для выдуманного урока с дробью и фейковой моделью."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from backend.api.__main__ import HOST, PORT
from backend.api.app import create_app
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.db import make_engine, make_sessions
from backend.triggers.assembly import Assembly

HINT = "На какое число делятся и числитель, и знаменатель?"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine()
    try:
        # Один запрос подсказки в демонстрации: сначала текст, затем решение контролёра.
        llm = FakeLLM([HINT, {"approved": True}])
        app.state.assembly = Assembly(make_sessions(engine), load_registry(BUILTIN_BLOCKS), llm)
        yield
    finally:
        await engine.dispose()


def main() -> None:
    app = create_app()
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
