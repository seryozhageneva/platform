"""Сборка: соединяет ядро с настоящими базой, блоками и ИИ-моделью (ADR 0006, ADR 0013).

Движок, хранилище, реестр и слой моделей друг о друге не знают — каждый видит только
контракты. Здесь они встречаются: `Assembly` держит всё, что нужно для запуска, и выдаёт
готовый движок. Ею пользуются триггеры и API.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from backend.core.contracts.interfaces import LLMClient
from backend.core.contracts.run import Done, RunContext, Waiting
from backend.core.engine import Engine, LoadedBlock
from backend.core.registry import BUILTIN_BLOCKS, Registry, load_registry
from backend.llm.factory import make_llm
from backend.models.db import Sessions, make_engine, make_sessions
from backend.models.llm_calls import LLMCallRepository
from backend.models.pipelines import PipelineRepository
from backend.models.run_store import PgRunStore
from backend.models.users import UserRepository

logger = logging.getLogger(__name__)


class Assembly:
    def __init__(
        self, sessions: Sessions, registry: Registry, llm: LLMClient | None = None
    ) -> None:
        self.registry = registry
        self.users = UserRepository(sessions)
        self.pipelines = PipelineRepository(sessions)
        self.runs = PgRunStore(sessions)
        self._llm = llm
        self._blocks = {name: _tagging(block) for name, block in registry.blocks.items()}

    def engine(self) -> Engine:
        """Движок с настоящим хранилищем. Он ничего не помнит, поэтому на каждый раз новый."""
        return Engine(self.runs, self._blocks, llm=self._llm)


def _tagging(block: LoadedBlock) -> LoadedBlock:
    """Тот же блок, но модель он получает с пометкой своего запуска и узла (ADR 0013).

    Движок выдаёт всем блокам одну модель и узел ей не сообщает. Запуск и узел есть в
    `context`, поэтому пометку ставит сборка — так вызов попадает в журнал вызовов с ними.
    """

    async def run(
        inputs: dict[str, Any], config: dict[str, Any], context: RunContext
    ) -> Done | Waiting:
        # Пометку умеет ставить слой моделей; у фейковой модели из тестов такого метода нет.
        bound = getattr(context.llm, "bound", None)
        if bound is not None:
            tagged = bound(run_id=context.run_id, node_id=context.node_id)
            context = context.model_copy(update={"llm": tagged})
        return await block.run(inputs, config, context)

    return LoadedBlock(block.manifest, run)


@asynccontextmanager
async def open_assembly() -> AsyncIterator[Assembly]:
    """Сборка по настройкам из `.env`: рабочая база, встроенные блоки, выбранная модель."""
    engine = make_engine()
    sessions = make_sessions(engine)
    llm = make_llm(call_log=LLMCallRepository(sessions))
    registry = load_registry(BUILTIN_BLOCKS)
    for problem in registry.problems:
        logger.warning("блок не загружен: %s", problem)
    try:
        yield Assembly(sessions, registry, llm)
    finally:
        await llm.aclose()
        await engine.dispose()
