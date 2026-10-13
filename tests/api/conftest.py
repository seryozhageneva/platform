"""Общее для тестов API: сервер с тестовой базой, фейковыми блоками и моделью-заглушкой.

Модель — заглушка провайдера: в сеть она не ходит. Запросы идут через `TestClient` — без
настоящего сетевого порта. Сами фейковые блоки и пайплайны из них — в `api_fakes.py`.
"""

import sys
import uuid
from collections.abc import Callable, Iterator

import pytest
from api_fakes import FAKE_BLOCKS, write_blocks
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.core.registry import Registry, load_registry
from backend.llm.client import PlatformLLM
from backend.llm.providers import StubProvider
from backend.models.llm_calls import LLMCallRepository
from backend.triggers.assembly import Assembly


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
def client_of(sessions) -> Callable[[Registry], TestClient]:
    """Сервер с указанным реестром блоков; база и модель-заглушка у всех общие."""

    def make(registry: Registry) -> TestClient:
        llm = PlatformLLM(StubProvider(), call_log=LLMCallRepository(sessions))
        return TestClient(create_app(Assembly(sessions, registry, llm)))

    return make


@pytest.fixture
def client(client_of, registry_of) -> TestClient:
    return client_of(registry_of())


@pytest.fixture
def me(teacher) -> dict[str, str]:
    """Заголовок «кто спрашивает» для преподавателя А."""
    return {"X-Teacher-Id": str(teacher.id)}


@pytest.fixture
def stranger(other_teacher) -> dict[str, str]:
    return {"X-Teacher-Id": str(other_teacher.id)}
