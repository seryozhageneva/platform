"""Приложение API v1 (ADR 0013).

`create_app()` без аргументов собирает платформу по настройкам из `.env` при старте
сервера; тесты передают готовую сборку с тестовой базой и фейковыми блоками.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.api import pipelines, runs
from backend.api.errors import ApiError
from backend.api.schemas import ErrorOut, ProblemOut
from backend.core.contracts.base import explain
from backend.triggers.assembly import Assembly, open_assembly

PREFIX = "/api/v1"


def create_app(assembly: Assembly | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if assembly is not None:
            yield
            return
        async with open_assembly() as opened:
            app.state.assembly = opened
            yield

    app = FastAPI(
        title="Платформа учебных пайплайнов",
        version="1",
        lifespan=lifespan,
        # Одна схема на модель и в запросе, и в ответе: клиенту фронтенда нужен один `Pipeline`.
        separate_input_output_schemas=False,
    )
    app.state.assembly = assembly

    api = APIRouter(prefix=PREFIX)
    api.include_router(pipelines.router)
    api.include_router(runs.router)

    @api.get("/health", tags=["Служебное"], summary="Сервер работает")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api)
    app.add_exception_handler(ApiError, _refused)
    app.add_exception_handler(RequestValidationError, _bad_request)
    app.add_exception_handler(HTTPException, _no_such_request)
    return app


def _answer(status: int, error: ErrorOut) -> JSONResponse:
    return JSONResponse(error.model_dump(mode="json"), status_code=status)


async def _refused(request: Request, error: ApiError) -> JSONResponse:
    problems = [ProblemOut.of(problem) for problem in error.problems]
    return _answer(error.status, ErrorOut(message=error.message, problems=problems))


async def _bad_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """Запрос не по формату: те же понятные строки, что и при разборе файла пайплайна."""
    if any(item["type"] == "json_invalid" for item in error.errors()):
        return _answer(422, ErrorOut(message="тело запроса — не JSON"))
    problems = [
        ProblemOut(code="bad_format", message=text.removeprefix("body.")) for text in explain(error)
    ]
    return _answer(422, ErrorOut(message="запрос не соответствует формату", problems=problems))


_NO_SUCH_REQUEST = {404: "такого адреса у API нет", 405: "этот адрес не принимает такой запрос"}


async def _no_such_request(request: Request, error: HTTPException) -> JSONResponse:
    """Отказ самого FastAPI — неизвестный адрес или метод — в том же виде, что и остальные."""
    message = _NO_SUCH_REQUEST.get(error.status_code, str(error.detail))
    return _answer(error.status_code, ErrorOut(message=message))
