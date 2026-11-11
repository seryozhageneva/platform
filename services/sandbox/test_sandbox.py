import json

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


def test_infrastructure_error_and_oversized_request_are_http_errors(monkeypatch):
    async def execute(*_args, **_kwargs):
        raise SandboxError("приватный текст сбоя")

    monkeypatch.setattr(app, "execute", execute)
    client = TestClient(app.create_app())
    response = client.post("/run", json=request_data())
    assert response.status_code == 503
    assert "приватный текст" not in response.text
    assert client.post("/run", content=b"x" * (app.MAX_REQUEST_BYTES + 1)).status_code == 413
