"""Сборка: соединяет ядро с настоящими базой, блоками и ИИ-моделью (ADR 0006, ADR 0013).

Движок, хранилище, реестр и слой моделей друг о друге не знают — каждый видит только
контракты. Здесь они встречаются: `Assembly` держит всё, что нужно для запуска, и выдаёт
готовый движок. Ею пользуются триггеры и API.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from backend.core.contracts.interfaces import LLMClient
from backend.core.contracts.manifest import Kind, Manifest
from backend.core.contracts.ports import Answer, PortType
from backend.core.contracts.run import Done, RunContext, Waiting
from backend.core.engine import Engine, LoadedBlock
from backend.core.registry import BUILTIN_BLOCKS, Registry, load_registry
from backend.llm.factory import make_llm
from backend.models.assignments import AssignmentRepository
from backend.models.auth import AuthRepository
from backend.models.db import Sessions, make_engine, make_sessions
from backend.models.llm_calls import LLMCallRepository
from backend.models.pipelines import PipelineRepository
from backend.models.platform_store import PgPlatformStore
from backend.models.run_store import PgRunStore
from backend.models.submissions import SubmissionRepository
from backend.models.tasks import TaskRepository
from backend.models.users import UserRepository

logger = logging.getLogger(__name__)


class Assembly:
    def __init__(
        self,
        sessions: Sessions,
        registry: Registry,
        llm: LLMClient | None = None,
        *,
        lock_sessions: Sessions | None = None,
    ) -> None:
        self.registry = registry
        self._sessions = sessions
        self.assignments = AssignmentRepository(sessions, lock_sessions=lock_sessions)
        self.users = UserRepository(sessions)
        self.auth = AuthRepository(sessions)
        self.pipelines = PipelineRepository(sessions)
        self.tasks = TaskRepository(sessions)
        self.runs = PgRunStore(sessions)
        self.submissions = SubmissionRepository(sessions)
        self._llm = llm
        self._blocks = {name: self._serviced(block) for name, block in registry.blocks.items()}

    def engine(
        self,
        *,
        assignment_id: uuid.UUID | None = None,
        approval: tuple[uuid.UUID, str, dict[str, Any]] | None = None,
    ) -> Engine:
        """Движок с хранилищем. Буфер записей одного шага принадлежит этому движку."""
        if assignment_id is None and approval is None:
            return Engine(self.runs, self._blocks, llm=self._llm)
        store = PgRunStore(self._sessions, assignment_id=assignment_id)
        if approval is not None:
            store.stage_approval(*approval)
        blocks = (
            self._blocks
            if assignment_id is None
            else {
                name: self._serviced(block, student_store=store)
                for name, block in self.registry.blocks.items()
            }
        )
        return Engine(store, blocks, llm=self._llm)

    def _serviced(
        self, block: LoadedBlock, *, student_store: PgRunStore | None = None
    ) -> LoadedBlock:
        """Тот же блок, но перед вызовом сборка кладёт в `context` службы этого запуска.

        Модель блок получает с пометкой своего запуска и узла (ADR 0013): движок выдаёт всем
        блокам одну модель и узел ей не сообщает, а запуск и узел есть в `context`, — так
        вызов попадает в журнал вызовов с ними. Хранилище платформы — ограниченное
        преподавателем этого запуска (ADR 0014, ADR 0015): чужих задач блок не увидит.

        Если блок ждал ученика и принял его ответ, ответ записывается в работы учеников
        (ADR 0016): у блока хранилище только на чтение, а переспрос работой не считается.
        """
        tasks = self.tasks
        record = self._record_answers

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
            result = await block.run(inputs, config, context)
            await record(block.manifest, context, result, student_store=student_store)
            return result

        return replace(block, run=run)

    async def _record_answers(
        self,
        manifest: Manifest,
        context: RunContext,
        result: Done | Waiting,
        *,
        student_store: PgRunStore | None,
    ) -> None:
        """Записывает ответы ученика, которые принял блок, ждавший ученика (ADR 0016)."""
        accepted = (
            manifest.kind is Kind.INTERACTIVE
            and context.human_response is not None
            and isinstance(result, Done)
        )
        # Работа принадлежит преподавателю запуска; без него записать её некому.
        if not accepted or context.teacher_id is None:
            return
        for port in manifest.outputs:
            if port.type is not PortType.ANSWER or port.is_list or port.name not in result.outputs:
                continue
            try:
                answer = Answer.model_validate(result.outputs[port.name])
            except ValidationError:
                # Такой выход движок не пропустит и остановит запуск — записывать нечего.
                continue
            owner_id = uuid.UUID(context.teacher_id)
            run_id = uuid.UUID(context.run_id)
            student_id = uuid.UUID(context.student_id) if context.student_id else None
            if student_store is not None:
                student_store.stage_submission(
                    self.submissions.answer_row(
                        owner_id,
                        answer,
                        run_id=run_id,
                        node_id=context.node_id,
                        student_id=student_id,
                    )
                )
                continue
            try:
                await self.submissions.add_answer(
                    owner_id, answer, run_id=run_id, node_id=context.node_id, student_id=student_id
                )
            except Exception as error:
                # Текст ошибки базы может содержать ответ ученика.
                raise RuntimeError(
                    f"не удалось записать работу ученика ({type(error).__name__})"
                ) from None


@asynccontextmanager
async def open_assembly(*, llm: LLMClient | None = None) -> AsyncIterator[Assembly]:
    """Сборка для сервера с отдельным пулом соединений для блокировок урока."""
    async with AsyncExitStack() as resources:
        engine = make_engine()
        resources.push_async_callback(engine.dispose)
        lock_engine = make_engine(engine.url, pool_size=5, max_overflow=0, pool_timeout=2)
        resources.push_async_callback(lock_engine.dispose)
        sessions = make_sessions(engine)
        if llm is None:
            platform_llm = make_llm(call_log=LLMCallRepository(sessions))
            resources.push_async_callback(platform_llm.aclose)
            llm = platform_llm
        registry = load_registry(BUILTIN_BLOCKS)
        for problem in registry.problems:
            logger.warning("блок не загружен: %s", problem)
        yield Assembly(sessions, registry, llm, lock_sessions=make_sessions(lock_engine))
