"""Сборка: соединяет ядро с настоящими базой, блоками и ИИ-моделью (ADR 0006, ADR 0013).

Движок, хранилище, реестр и слой моделей друг о друге не знают — каждый видит только
контракты. Здесь они встречаются: `Assembly` держит всё, что нужно для запуска, и выдаёт
готовый движок. Ею пользуются триггеры и API.
"""

import logging
import uuid
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
from backend.models.platform_store import PgPlatformStore
from backend.models.run_store import PgRunStore
from backend.models.tasks import TaskRepository
from backend.models.users import UserRepository

logger = logging.getLogger(__name__)


class Assembly:
    def __init__(
        self, sessions: Sessions, registry: Registry, llm: LLMClient | None = None
    ) -> None:
        self.registry = registry
        self.users = UserRepository(sessions)
        self.pipelines = PipelineRepository(sessions)
        self.tasks = TaskRepository(sessions)
        self.runs = PgRunStore(sessions)
        self._llm = llm
        self._blocks = {name: self._serviced(block) for name, block in registry.blocks.items()}

    def engine(self) -> Engine:
        """Движок с настоящим хранилищем. Он ничего не помнит, поэтому на каждый раз новый."""
        return Engine(self.runs, self._blocks, llm=self._llm)

    def _serviced(self, block: LoadedBlock) -> LoadedBlock:
        """Тот же блок, но перед вызовом сборка кладёт в `context` службы этого запуска.

        Модель блок получает с пометкой своего запуска и узла (ADR 0013): движок выдаёт всем
        блокам одну модель и узел ей не сообщает, а запуск и узел есть в `context`, — так
        вызов попадает в журнал вызовов с ними. Хранилище платформы — ограниченное
        преподавателем этого запуска (ADR 0014, ADR 0015): чужих задач блок не увидит.
        """
        tasks = self.tasks

        async def run(
            inputs: dict[str, Any], config: dict[str, Any], context: RunContext
        ) -> Done | Waiting:
            services: dict[str, Any] = {}
            # Пометку умеет ставить слой моделей; у фейковой модели из тестов такого метода нет.
            bound = getattr(context.llm, "bound", None)
            if bound is not None:
                services["llm"] = bound(run_id=context.run_id, node_id=context.node_id)
            # Без преподавателя хранилище не выдаётся: ограничить его было бы некем.
            if context.teacher_id is not None:
                services["store"] = PgPlatformStore(tasks, uuid.UUID(context.teacher_id))
            if services:
                context = context.model_copy(update=services)
            return await block.run(inputs, config, context)

        return LoadedBlock(block.manifest, run)


@asynccontextmanager
async def open_assembly() -> AsyncIterator[Assembly]:
    """Сборка по настройкам из `.env`: рабочая база, встроенные блоки, выбранная модель."""
    engine = make_engine()
    try:
        sessions = make_sessions(engine)
        llm = make_llm(call_log=LLMCallRepository(sessions))
        try:
            registry = load_registry(BUILTIN_BLOCKS)
            for problem in registry.problems:
                logger.warning("блок не загружен: %s", problem)
            yield Assembly(sessions, registry, llm)
        finally:
            await llm.aclose()
    finally:
        await engine.dispose()
