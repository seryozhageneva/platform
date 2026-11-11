"""Запускает один тест в одноразовом контейнере с ограниченными ресурсами."""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

IMAGE = "platform-code-runner:local"
OUTPUT_LIMIT = 32 * 1024
DOCKER_TIMEOUT = 5


class SandboxError(RuntimeError):
    """Не удалось запустить или остановить контейнер."""


class _OutputLimit(Exception):
    pass


@dataclass(frozen=True)
class Execution:
    stdout: bytes = b""
    failure: str | None = None


async def _read(stream: asyncio.StreamReader) -> bytes:
    data = bytearray()
    while chunk := await stream.read(4096):
        data.extend(chunk)
        if len(data) > OUTPUT_LIMIT:
            raise _OutputLimit
    return bytes(data)


async def _write(stream: asyncio.StreamWriter, payload: bytes) -> None:
    try:
        stream.write(payload)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        stream.close()


async def _docker(
    *args: str, timeout: int = DOCKER_TIMEOUT, payload: bytes = b""
) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        raise SandboxError("Docker недоступен") from None
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdout = asyncio.create_task(_read(process.stdout))
    stderr = asyncio.create_task(_read(process.stderr))
    writer = asyncio.create_task(_write(process.stdin, payload))
    try:
        async with asyncio.timeout(timeout):
            await asyncio.gather(stdout, stderr, writer)
            return await process.wait(), stdout.result()
    finally:
        for task in (stdout, stderr, writer):
            task.cancel()
        await asyncio.gather(stdout, stderr, writer, return_exceptions=True)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.communicate()


async def _control(*args: str) -> bytes:
    try:
        status, output = await _docker(*args)
    except (TimeoutError, _OutputLimit):
        raise SandboxError("Docker не ответил на управляющую команду") from None
    if status != 0:
        raise SandboxError("Docker не смог выполнить управляющую команду")
    return output


async def execute(code: str, stdin: str, *, seconds: int, memory_mb: int) -> Execution:
    name = f"platform-code-{uuid4().hex}"
    payload = json.dumps({"code": code, "stdin": stdin}, ensure_ascii=True).encode()
    try:
        await _control(
            "create",
            "--name",
            name,
            "--pull=never",
            "--interactive",
            "--network=none",
            "--read-only",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=1m,mode=1777",
            "--workdir=/tmp",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=16",
            "--cpus=1",
            f"--memory={memory_mb}m",
            f"--memory-swap={memory_mb}m",
            "--log-driver=none",
            IMAGE,
        )
        try:
            status, stdout = await _docker("start", "-ai", name, timeout=seconds, payload=payload)
        except TimeoutError:
            return Execution(failure="Превышен лимит времени.")
        except _OutputLimit:
            return Execution(failure="Превышен лимит вывода.")
        if status == 0:
            return Execution(stdout=stdout)
        state = json.loads(await _control("inspect", "--format={{json .State}}", name))
        if state["OOMKilled"]:
            return Execution(failure="Превышен лимит памяти.")
        if state["Status"] == "exited" and not state["Error"] and state["ExitCode"] != 0:
            return Execution(failure="Программа завершилась с ошибкой.")
        raise SandboxError("Docker не смог выполнить тест")
    finally:
        await _remove(name)


async def _remove(name: str) -> None:
    # Удаляем по имени даже после прерванной команды create или start.
    try:
        status, _ = await _docker("rm", "-f", name)
        if status != 0:
            # Если контейнер так и не создался, удалять нечего.
            remaining = await _control("ps", "-aq", f"--filter=name=^/{name}$")
            if remaining.strip():
                raise SandboxError("Docker не смог удалить контейнер")
    except (TimeoutError, _OutputLimit):
        raise SandboxError("Docker не смог удалить контейнер") from None
