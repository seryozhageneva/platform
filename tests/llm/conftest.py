"""Общее для тестов слоя ИИ-моделей."""

import pytest
from llm_doubles import MemoryCallLog


@pytest.fixture
def call_log() -> MemoryCallLog:
    return MemoryCallLog()
