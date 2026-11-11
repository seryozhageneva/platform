"""HTTP-блок проверки Python-кода. Сервис запускается рядом с локальным Docker."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, TypeAdapter, ValidationError, field_validator

from backend.core.contracts.base import Strict
from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import Answer, AnswerForm, CheckMethod, Task, Verdict
from backend.core.contracts.run import Done, RunRequest
from services.sandbox.runner import OUTPUT_LIMIT, SandboxError, execute

MANIFEST = load_manifest(
    Path(__file__).resolve().parents[2] / "blocks" / "check" / "code_tests" / "block.yaml"
)
# Поле Task.tests содержит JSON-строку внутри JSON запроса. Восемь тестов
# по 32 КиБ на вход и выход должны помещаться даже после двойного экранирования.
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_CODE_BYTES = 32 * 1024
MAX_TESTS = 8
MAX_WAITING = 8
SLOT_TIMEOUT = 60


class CodeTest(Strict):
    stdin: str = Field(max_length=OUTPUT_LIMIT)
    stdout: str = Field(max_length=OUTPUT_LIMIT)

    @field_validator("stdin", "stdout")
    @classmethod
    def fits_byte_limit(cls, value: str) -> str:
        if len(value.encode()) > OUTPUT_LIMIT:
            raise ValueError("вход и ожидаемый вывод должны укладываться в 32 КиБ UTF-8")
        return value


class Limits(Strict):
    time_limit_seconds: int = Field(default=5, strict=True, ge=1, le=5)
    memory_limit_mb: int = Field(default=128, strict=True, ge=16, le=256)


_TESTS = TypeAdapter(list[CodeTest])


def create_app() -> FastAPI:
    app = FastAPI(title="Песочница Python")
    slots = asyncio.Semaphore(2)
    waiting = 0

    @app.get("/manifest")
    async def manifest() -> dict:
        return MANIFEST.model_dump(mode="json", by_alias=True, exclude_none=True)

    @app.post("/run")
    async def run(request: Request) -> Done:
        nonlocal waiting
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            raise HTTPException(415, "Ожидается application/json")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise HTTPException(413, "Запрос слишком большой")
            body.extend(chunk)
        try:
            run_request = RunRequest.model_validate_json(body)
            limits = Limits.model_validate(run_request.config)
            task = Task.model_validate(run_request.inputs.get("task"))
            answer = Answer.model_validate(run_request.inputs.get("answer"))
            tests = _TESTS.validate_json(task.tests or "[]")
        except ValidationError:
            raise HTTPException(422, "Проверьте входы, настройки и формат тестов") from None
        if task.check_method is not CheckMethod.CODE or not 1 <= len(tests) <= MAX_TESTS:
            raise HTTPException(422, f"Нужна задача на код с 1–{MAX_TESTS} тестами")
        if answer.task_id != task.id:
            raise HTTPException(422, "Ответ относится к другой задаче")
        if waiting >= MAX_WAITING:
            raise HTTPException(503, "Песочница занята")
        waiting += 1
        try:
            async with asyncio.timeout(SLOT_TIMEOUT):
                await slots.acquire()
        except TimeoutError:
            raise HTTPException(503, "Песочница занята") from None
        finally:
            waiting -= 1
        try:
            return await _grade(task.id, answer, tests, limits)
        except SandboxError:
            raise HTTPException(503, "Песочница не смогла запустить тесты") from None
        finally:
            slots.release()

    return app


async def _grade(task_id: str, answer: Answer, tests: list[CodeTest], limits: Limits) -> Done:
    code = answer.text or ""
    if answer.form is not AnswerForm.CODE or not code.strip():
        return _verdict(task_id, 0, len(tests), "Отправьте программу в форме «Код».")
    if len(code.encode()) > MAX_CODE_BYTES:
        return _verdict(task_id, 0, len(tests), "Программа слишком большая.")
    passed = 0
    failure = None
    for test in tests:
        execution = await execute(
            code, test.stdin, seconds=limits.time_limit_seconds, memory_mb=limits.memory_limit_mb
        )
        if execution.failure:
            failure = failure or execution.failure
        elif execution.stdout.rstrip(b"\r\n") == test.stdout.encode().rstrip(b"\r\n"):
            passed += 1
    comment = f"Пройдено тестов: {passed} из {len(tests)}."
    if failure:
        comment = f"{comment} {failure}"
    return _verdict(task_id, passed, len(tests), comment)


def _verdict(task_id: str, passed: int, total: int, comment: str) -> Done:
    correct = passed == total
    verdict = Verdict(
        task_id=task_id, correct=correct, score=passed, max_score=total, comment=comment
    )
    return Done(
        outcome="correct" if correct else "wrong",
        outputs={"verdict": verdict.model_dump(mode="json")},
    )


app = create_app()
