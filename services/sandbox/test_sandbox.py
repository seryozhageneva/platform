import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.core.contracts.manifest import Manifest
from services.sandbox import app
from services.sandbox.runner import Execution, SandboxError


def request_data():
    return {
        "inputs": {
            "task": {
                "id": "sum",
                "subject": "Информатика",
                "topic": "Ввод",
                "difficulty": 1,
                "statement": "Напечатай число.",
                "check_method": "code",
                "tests": json.dumps(
                    [
                        {"stdin": "1\n", "stdout": "1"},
                        {"stdin": "2\n", "stdout": "2"},
                    ]
                ),
            },
            "answer": {"task_id": "sum", "form": "code", "text": "print(input())"},
        },
        "context": {"run_id": "run", "pipeline_id": "lesson", "node_id": "grade"},
    }


def test_manifest_matches_registry():
    response = TestClient(app.create_app()).get("/manifest")
    assert response.status_code == 200
    assert Manifest.model_validate(response.json()) == app.MANIFEST


@pytest.mark.parametrize(
    ("second", "score", "outcome"),
    [
        (Execution(stdout=b"2\n"), 2, "correct"),
        (Execution(stdout=b"3"), 1, "wrong"),
        (Execution(failure="Превышен лимит времени."), 1, "wrong"),
    ],
)
def test_verdict_counts_passed_tests(monkeypatch, second, score, outcome):
    async def execute(code, stdin, *, seconds, memory_mb):
        assert code == "print(input())"
        assert seconds == 5 and memory_mb == 128
        return Execution(stdout=b"1\n") if stdin == "1\n" else second

    monkeypatch.setattr(app, "execute", execute)
    response = TestClient(app.create_app()).post("/run", json=request_data())
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == outcome
    verdict = result["outputs"]["verdict"]
    assert verdict["score"] == score
    assert verdict["max_score"] == 2
    assert verdict["preliminary"] is False
    if second.failure:
        assert second.failure in verdict["comment"]


def test_bad_test_format_and_invalid_limits_fail_before_execution(monkeypatch):
    async def execute(*_args, **_kwargs):
        pytest.fail("ошибочные данные не должны попасть в контейнер")

    monkeypatch.setattr(app, "execute", execute)
    client = TestClient(app.create_app())
    payload = request_data()
    payload["config"] = {"time_limit_seconds": 6}
    assert client.post("/run", json=payload).status_code == 422
    payload["config"] = {}
    payload["inputs"]["task"]["tests"] = "assert True"
    assert client.post("/run", json=payload).status_code == 422
    payload["inputs"]["task"]["tests"] = json.dumps(
        [{"stdin": "", "stdout": "я" * app.OUTPUT_LIMIT}], ensure_ascii=False
    )
    assert client.post("/run", json=payload).status_code == 422


def test_all_eight_tests_fit_at_the_byte_limit(monkeypatch):
    data = "\x00" * app.OUTPUT_LIMIT
    calls = 0

    async def execute(_code, stdin, **_limits):
        nonlocal calls
        calls += 1
        assert stdin == data
        return Execution(stdout=data.encode())

    monkeypatch.setattr(app, "execute", execute)
    payload = request_data()
    payload["inputs"]["task"]["tests"] = json.dumps(
        [{"stdin": data, "stdout": data}] * app.MAX_TESTS
    )
    response = TestClient(app.create_app()).post("/run", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "correct"
    assert calls == app.MAX_TESTS


def test_third_concurrent_request_waits_for_a_slot(monkeypatch):
    async def check():
        started = 0
        two_running = asyncio.Event()
        release = asyncio.Event()

        async def execute(_code, stdin, **_limits):
            nonlocal started
            if stdin == "1\n":
                started += 1
                if started == 2:
                    two_running.set()
                await release.wait()
            return Execution(stdout=stdin.encode())

        monkeypatch.setattr(app, "execute", execute)
        transport = httpx.ASGITransport(app=app.create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with asyncio.timeout(3):
                first = asyncio.create_task(client.post("/run", json=request_data()))
                second = asyncio.create_task(client.post("/run", json=request_data()))
                await two_running.wait()
                third = asyncio.create_task(client.post("/run", json=request_data()))
                try:
                    done, _ = await asyncio.wait({third}, timeout=0.02)
                    assert not done and started == 2
                finally:
                    release.set()
                responses = await asyncio.gather(first, second, third)
        assert [response.status_code for response in responses] == [200, 200, 200]
        assert started == 3

    asyncio.run(check())


def test_infrastructure_error_and_oversized_request_are_http_errors(monkeypatch):
    async def execute(*_args, **_kwargs):
        raise SandboxError("приватный текст сбоя")

    monkeypatch.setattr(app, "execute", execute)
    client = TestClient(app.create_app())
    response = client.post("/run", json=request_data())
    assert response.status_code == 503
    assert "приватный текст" not in response.text
    assert (
        client.post(
            "/run",
            content=b"x" * (app.MAX_REQUEST_BYTES + 1),
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )


def test_run_rejects_plain_text_even_if_it_contains_json():
    response = TestClient(app.create_app()).post(
        "/run", content=json.dumps(request_data()), headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
