"""Локальный сервер для выдуманного урока с дробью и фейковой моделью."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from backend.api.__main__ import HOST, PORT
from backend.api.app import create_app
from backend.core.contracts.testing import FakeLLM
from backend.triggers.assembly import open_assembly

HINT = "На какое число делятся и числитель, и знаменатель?"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Один запрос подсказки в демонстрации: сначала текст, затем решение контролёра.
    llm = FakeLLM([HINT, {"approved": True}])
    async with open_assembly(llm=llm) as assembly:
        app.state.assembly = assembly
        yield


def main() -> None:
    app = create_app()
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
