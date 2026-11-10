"""Общее для тестов API: сервер с тестовой базой, фейковыми блоками и моделью-заглушкой.

Модель — заглушка провайдера: в сеть она не ходит. Запросы идут через `TestClient` — без
настоящего сетевого порта. Сами фейковые блоки и пайплайны из них — в `api_fakes.py`.
"""

import asyncio
import sys
import uuid
from collections.abc import Callable, Iterator

import pytest
from api_fakes import FAKE_BLOCKS, write_blocks
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.registry import Registry, load_registry
from backend.llm.client import PlatformLLM
from backend.llm.providers import StubProvider
from backend.models.auth import AuthRepository
from backend.models.llm_calls import LLMCallRepository
from backend.triggers.assembly import Assembly
from backend.triggers.queue import EnqueueLaunch


@pytest.fixture
def registry_of(tmp_path, monkeypatch) -> Iterator[Callable[..., Registry]]:
    """Реестр из названных фейковых блоков; без названий — из всех."""
    monkeypatch.syspath_prepend(tmp_path)
    roots: list[str] = []

    def make(*names: str) -> Registry:
        # Имя у каждой папки своё: Python помнит загруженные модули.
        root = tmp_path / f"api_blocks_{uuid.uuid4().hex[:8]}"
        roots.append(root.name)
        write_blocks(root, list(names or FAKE_BLOCKS))
        registry = load_registry(root)
        assert registry.problems == []
        return registry

    yield make
    for name in [name for name in sys.modules if name.split(".")[0] in roots]:
        del sys.modules[name]


@pytest.fixture
def client_of(sessions):
    """Сервер с указанным реестром блоков; база и модель-заглушка у всех общие."""

    async def accept(run_id: uuid.UUID) -> None:
        pass  # Отдельный вызов рабочего процесса делает помощник теста.

    def make(registry: Registry, *, enqueue: EnqueueLaunch = accept) -> TestClient:
        llm = PlatformLLM(StubProvider(), call_log=LLMCallRepository(sessions))
        return TestClient(
            create_app(Assembly(sessions, registry, llm), enqueue=enqueue),
            headers={"Origin": "http://testserver"},
        )

    return make


@pytest.fixture
def client(client_of, registry_of) -> TestClient:
    return client_of(registry_of())


def _session_headers(sessions, user) -> dict[str, str]:
    token, _ = asyncio.run(AuthRepository(sessions).start_teacher(user.id))
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


@pytest.fixture
def me(sessions, teacher) -> dict[str, str]:
    return _session_headers(sessions, teacher)


@pytest.fixture
def stranger(sessions, other_teacher) -> dict[str, str]:
    return _session_headers(sessions, other_teacher)
