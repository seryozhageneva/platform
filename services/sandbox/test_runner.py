"""Как песочница называет причину, по которой программа не дошла до конца, — без Docker.

Docker подменён: тест задаёт код выхода и состояние контейнера, которое вернул бы
`docker inspect`. Так проверяется случай из CI: ядро убило программу за превышение памяти,
а отметка OOMKilled ещё не успела прийти.
"""

import asyncio
import json

import pytest

from services.sandbox import runner


def fake_docker(status: int, state: dict):
    async def docker(*args, timeout=runner.DOCKER_TIMEOUT, payload=b""):
        if args[0] == "start":
            return status, b""
        if args[0] == "inspect":
            return 0, json.dumps(state).encode()
        # create, rm и ps после удаления: контейнера больше нет.
        return 0, b""

    return docker


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [
        # Отметка уже пришла.
        (137, {"OOMKilled": True, "Status": "exited", "Error": "", "ExitCode": 137}, "памяти"),
        # Отметка опоздала: код 137 всё равно означает превышение памяти.
        (137, {"OOMKilled": False, "Status": "exited", "Error": "", "ExitCode": 137}, "памяти"),
        # Обычная ошибка программы — например, необработанное исключение.
        (1, {"OOMKilled": False, "Status": "exited", "Error": "", "ExitCode": 1}, "с ошибкой"),
    ],
)
def test_failure_reason(monkeypatch, status, state, expected):
    monkeypatch.setattr(runner, "_docker", fake_docker(status, state))
    result = asyncio.run(runner.execute("x = 1", "", seconds=1, memory_mb=32))
    assert result.stdout == b""
    assert expected in result.failure
