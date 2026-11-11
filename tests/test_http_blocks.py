import asyncio
import json

import httpx
import pytest

from backend.core.contracts.run import Done, RunContext
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.triggers.http_blocks import http_connector


def test_http_connector_serializes_contract_without_services():
    async def handler(request):
        assert request.url == "http://sandbox.test/blocks/run"
        assert json.loads(request.content) == {
            "inputs": {"answer": "code"},
            "config": {"time_limit_seconds": 1},
            "context": {
                "run_id": "r",
                "node_id": "n",
                "pipeline_id": "p",
                "params": {},
                "student_id": None,
                "teacher_id": None,
                "attempt": 1,
                "shown": None,
                "human_response": None,
            },
        }
        return httpx.Response(200, json={"status": "done", "outcome": "wrong"})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            registry = load_registry(
                BUILTIN_BLOCKS,
                {"http": http_connector(client, sandbox_url="http://sandbox.test/blocks/")},
            )
            assert registry.problems == []
            block = registry.blocks["check.code_tests"]
            result = await block.run(
                {"answer": "code"},
                {"time_limit_seconds": 1},
                RunContext(run_id="r", node_id="n", pipeline_id="p", llm=FakeLLM([])),
            )
            assert result == Done(outcome="wrong")

    asyncio.run(check())


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (503, "ошибку 503"),
        (200, "неверном формате"),
        (None, "недоступен"),
    ],
)
def test_http_service_failure_is_block_error(status, match):
    async def handler(request):
        if status is None:
            raise httpx.ConnectError("частный адрес", request=request)
        return httpx.Response(status, text="частные данные")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            registry = load_registry(BUILTIN_BLOCKS, {"http": http_connector(client)})
            with pytest.raises(RuntimeError, match=match) as caught:
                await registry.blocks["check.code_tests"].run(
                    {}, {}, RunContext(run_id="r", node_id="n", pipeline_id="p")
                )
            assert "частн" not in str(caught.value)

    asyncio.run(check())
