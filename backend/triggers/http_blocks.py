"""Преобразует HTTP-сервис с контрактом блока в функцию run для реестра."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from backend.core.contracts.manifest import HttpRuntime, Manifest
from backend.core.contracts.run import BlockRun, RunContext, RunRequest, RunResult

HTTP_BLOCK_TIMEOUT = 240
_RESULT = TypeAdapter(RunResult)


def http_connector(
    client: httpx.AsyncClient, *, sandbox_url: str | None = None
) -> Callable[[Manifest], BlockRun]:
    def connect(manifest: Manifest) -> BlockRun:
        assert isinstance(manifest.runtime, HttpRuntime)
        base_url = manifest.runtime.url
        if manifest.id == "check.code_tests" and sandbox_url:
            base_url = sandbox_url
        url = httpx.URL(base_url)
        if url.scheme not in ("http", "https") or not url.host or url.query or url.fragment:
            raise ValueError("ожидается базовый адрес HTTP-сервиса")
        endpoint = f"{str(url).rstrip('/')}/run"

        async def run(
            inputs: dict[str, Any], config: dict[str, Any], context: RunContext
        ) -> RunResult:
            request = RunRequest(inputs=inputs, config=config, context=context)
            try:
                async with asyncio.timeout(HTTP_BLOCK_TIMEOUT):
                    response = await client.post(
                        endpoint,
                        content=request.model_dump_json(),
                        headers={"Content-Type": "application/json"},
                    )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(
                    f"HTTP-блок вернул ошибку {error.response.status_code}"
                ) from None
            except (httpx.RequestError, TimeoutError):
                raise RuntimeError("HTTP-блок недоступен или не ответил вовремя") from None
            try:
                return _RESULT.validate_json(response.content)
            except ValidationError:
                raise RuntimeError("HTTP-блок вернул результат в неверном формате") from None

        return run

    return connect
