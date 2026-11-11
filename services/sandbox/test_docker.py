"""Проверяет изоляцию на настоящем Docker с собранным образом."""

import asyncio
import os
import subprocess

import pytest

from services.sandbox.runner import execute

pytestmark = pytest.mark.skipif(
    os.environ.get("PLATFORM_TEST_DOCKER") != "1", reason="нужны Docker и образ песочницы"
)


def containers():
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter=name=^/platform-code-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def test_python_runs_without_network_platform_files_or_privileges(tmp_path):
    sentinel = tmp_path / "platform-sandbox-sentinel"
    sentinel.write_text("файл вне контейнера")
    code = f"""import os, socket, sys
assert os.getuid() != 0
assert [name for _, name in socket.if_nameindex()] == ["lo"]
assert not os.path.exists("/var/run/docker.sock")
assert not os.path.exists({str(sentinel)!r})
assert os.statvfs("/opt").f_flag & os.ST_RDONLY
assert not any(key.lower().endswith("_proxy") for key in os.environ)
print(sum(map(int, sys.stdin.read().split())))
"""
    before = containers()
    result = asyncio.run(execute(code, "2 3\n", seconds=5, memory_mb=128))
    assert result.failure is None
    assert result.stdout == b"5\n"
    assert containers() == before


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("while True: pass", "Превышен лимит времени."),
        ("x = bytearray(256 * 1024 * 1024)", "Превышен лимит памяти."),
        ("while True: print('x' * 4096)", "Превышен лимит вывода."),
        (
            "raise ValueError('текст не должен попасть в вердикт')",
            "Программа завершилась с ошибкой.",
        ),
    ],
)
def test_docker_limits_and_cleanup(code, expected):
    before = containers()
    result = asyncio.run(execute(code, "", seconds=2, memory_mb=32))
    assert result.failure == expected
    assert result.stdout == b""
    assert containers() == before
