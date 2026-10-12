"""Движок v1: выполняет пайплайн узел за узлом и после каждого узла сохраняет состояние.

Умеет прямую цепочку блоков. Развилка, «для каждого», ограничитель цикла и пауза на человеке
появятся в задаче 05; встретив их, движок останавливает запуск с понятной ошибкой, а не
пропускает молча. Решения — ADR 0008.

Движок знает только контракты (правило 4): хранилище, блоки и пайплайн ему передают снаружи.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.core.contracts.interfaces import LLMClient
from backend.core.contracts.manifest import Manifest
from backend.core.contracts.pipeline import (
    Binding,
    BlockNode,
    ForEachNode,
    Pipeline,
    SwitchNode,
    Transition,
)
from backend.core.contracts.ports import Event, value_problems
from backend.core.contracts.run import (
    BlockEvent,
    BlockRun,
    Done,
    RunContext,
    Waiting,
    result_problems,
)
from backend.core.contracts.state import RunState, RunStatus, RunStore

NOT_YET = "движок пока не умеет {} — это появится в задаче 05"


@dataclass(frozen=True)
class LoadedBlock:
    """Блок, готовый к вызову: его манифест и функция `run`.

    Таблицу таких блоков движок получает при создании. Собирать её по файлам `block.yaml`
    будет реестр (задача 06); в тестах её составляют из фейковых блоков.
    """

    manifest: Manifest
    run: BlockRun


class NodeFailed(Exception):
    """Узел не удалось выполнить. Текст попадает в `RunState.error` и в журнал событий."""


class Engine:
    def __init__(
        self,
        store: RunStore,
        blocks: Mapping[str, LoadedBlock],
        *,
        llm: LLMClient | None = None,
    ) -> None:
        self._store = store
        self._blocks = blocks
        self._llm = llm

    async def start(
        self,
        pipeline: Pipeline,
        *,
        run_id: str,
        pipeline_id: str,
        pipeline_version: int,
        event: Event,
        params: Mapping[str, Any] | None = None,
        student_id: str | None = None,
        teacher_id: str | None = None,
    ) -> RunState:
        """Создаёт запуск и выполняет его, пока он не закончится или не остановится."""
        # Второй старт с тем же идентификатором затёр бы состояние и заново вызвал блоки.
        if await self._store.load(run_id) is not None:
            raise ValueError(f"запуск «{run_id}» уже есть: его продолжают, а не начинают заново")
        trigger = pipeline.trigger()
        first = _next(pipeline.transitions, trigger.id, None)
        state = RunState(
            run_id=run_id,
            pipeline_id=pipeline_id,
            pipeline_version=pipeline_version,
            # Триггер, из которого никуда не ведёт переход, — запуск без единого шага.
            status=RunStatus.RUNNING if first else RunStatus.DONE,
            params=_fill_params(pipeline, params or {}),
            student_id=student_id,
            teacher_id=teacher_id,
            current=[first] if first else [],
        )
        # Событие — выход триггера: блоки читают его по ссылке «узел_триггера.event».
        state.write(trigger.id, {"event": event.model_dump(mode="json")})
        await self._store.save(state)
        events = [BlockEvent(type="run_started", data={"trigger": event.trigger.value})]
        if not first:
            events.append(BlockEvent(type="run_done"))
        await self._store.append_events(run_id, trigger.id, events)
        return await self._advance(pipeline, state)

    async def resume(self, pipeline: Pipeline, run_id: str) -> RunState:
        """Продолжает запуск с того узла, на котором он остановился.

        Состояние читается из хранилища, поэтому продолжить может и другой экземпляр
        движка — например, после перезапуска сервера.
        """
        state = await self._store.load(run_id)
        if state is None:
            raise LookupError(f"запуск «{run_id}» не найден")
        # Законченный запуск продолжать некуда. Запуск на паузе продолжается ответом
        # человека, а это задача 05.
        if state.status in (RunStatus.DONE, RunStatus.WAITING):
            return state
        state.status, state.error = RunStatus.RUNNING, None
        return await self._advance(pipeline, state)

    async def _advance(self, pipeline: Pipeline, state: RunState) -> RunState:
        nodes = {node.id: node for node in pipeline.nodes}
        while state.current:
            node_id = state.current[0]
            try:
                outputs, outcome, block_events = await self._step(nodes.get(node_id), state)
            except NodeFailed as failure:
                return await self._fail(state, node_id, str(failure))
            before, order_before = state.ports.get(node_id), list(state.write_order)
            state.write(node_id, outputs)
            target = _next(pipeline.transitions, node_id, outcome)
            state.current = [target] if target else []
            own_events = [BlockEvent(type="node_done", data={"outcome": outcome})]
            if not target:
                # Подходящего перехода нет — ветка, а с ней и запуск, на этом заканчивается.
                state.status = RunStatus.DONE
                own_events.append(BlockEvent(type="run_done"))
            try:
                # Состояние сохраняется после каждого узла: при сбое теряется не больше шага.
                await self._store.save(state)
            except Exception as error:
                # Хранилище не приняло состояние — например, в выходе блока оказался символ,
                # который база не записывает. Шаг отменяется: запуск остаётся на этом узле без
                # его новых выходов. Текст ошибки хранилища в состояние не идёт: в нём могут
                # быть данные запуска.
                state.status, state.current = RunStatus.RUNNING, [node_id]
                if before is None:
                    del state.ports[node_id]
                else:
                    state.ports[node_id] = before
                state.write_order = order_before
                reason = f"не удалось сохранить состояние после узла ({type(error).__name__})"
                return await self._fail(state, node_id, reason)
            await self._journal(state.run_id, node_id, block_events, own_events)
        return state

    async def _fail(self, state: RunState, node_id: str, reason: str) -> RunState:
        """Останавливает запуск со статусом «ошибка».

        Текущий узел остаётся на месте: с него запуск можно будет продолжить.
        """
        reason = _storable(reason)
        state.status, state.error = RunStatus.ERROR, f"узел «{node_id}»: {reason}"
        try:
            await self._store.save(state)
        except Exception as error:
            # Хранилище не приняло сам текст ошибки. Сохраняется короткий: главное, чтобы
            # запуск не остался «выполняться». Не вышло и это — хранилище недоступно, и
            # исключение уходит вызывающему.
            reason = f"текст ошибки не удалось сохранить ({type(error).__name__})"
            state.error = f"узел «{node_id}»: {reason}"
            await self._store.save(state)
        failed = BlockEvent(type="node_failed", data={"error": reason})
        await self._journal(state.run_id, node_id, [], [failed])
        return state

    async def _journal(
        self, run_id: str, node_id: str, block_events: list[BlockEvent], own: list[BlockEvent]
    ) -> None:
        """Дописывает в журнал события блока и следом — события самого движка.

        Состояние к этому моменту уже сохранено, поэтому шаг из-за журнала не отменяется.
        Если хранилище не приняло события блока, в журнале остаётся отметка о потере.
        """
        try:
            await self._store.append_events(run_id, node_id, [*block_events, *own])
        except Exception as error:
            if not block_events:
                raise
            lost = BlockEvent(
                type="events_lost",
                data={"count": len(block_events), "reason": type(error).__name__},
            )
            await self._store.append_events(run_id, node_id, [lost, *own])

    async def _step(
        self, node: Any, state: RunState
    ) -> tuple[dict[str, Any], str, list[BlockEvent]]:
        """Один шаг: выполняет узел. Возвращает его выходы, исход и события; состояние не меняет."""
        if node is None:
            raise NodeFailed("такого узла нет в пайплайне")
        if isinstance(node, SwitchNode):
            raise NodeFailed(NOT_YET.format("выполнять развилку"))
        if isinstance(node, ForEachNode):
            raise NodeFailed(NOT_YET.format("выполнять «для каждого»"))
        if not isinstance(node, BlockNode):
            raise NodeFailed("узел-триггер не выполняется: с него запуск только начинается")
        if node.limit is not None:
            raise NodeFailed(NOT_YET.format("считать ограничитель"))
        block = self._blocks.get(node.block)
        if block is None:
            raise NodeFailed(f"блок «{node.block}» не найден")

        inputs = _inputs(node, block.manifest, state)
        config = _with_params(node.config, state.params)
        context = RunContext(
            run_id=state.run_id,
            node_id=node.id,
            pipeline_id=state.pipeline_id,
            params=state.params,
            student_id=state.student_id,
            teacher_id=state.teacher_id,
            llm=self._llm,
        )
        try:
            result = await block.run(inputs, config, context)
        except Exception as error:
            raise NodeFailed(
                f"блок «{node.block}» упал: {type(error).__name__}: {error}"
            ) from error

        outputs = _checked_outputs(block.manifest, result)
        return outputs, result.outcome, result.events


def _storable(text: str) -> str:
    """Текст без символов, которые не записываются в базу: нулевого и «битых» (ADR 0007).

    Такие символы попадают в текст ошибки, когда блок цитирует в ней свои данные —
    например, текст, извлечённый из PDF.
    """
    return text.replace("\x00", "\ufffd").encode("utf-8", "replace").decode("utf-8")


def _fill_params(pipeline: Pipeline, given: Mapping[str, Any]) -> dict[str, Any]:
    """Значения параметров запуска: заданные при старте, иначе — по умолчанию."""
    known = {param.name for param in pipeline.params}
    unknown = sorted(set(given) - known)
    if unknown:
        raise ValueError(f"у пайплайна нет параметра: {', '.join(unknown)}")
    values = {param.name: given.get(param.name, param.default) for param in pipeline.params}
    empty = sorted(name for name, value in values.items() if value is None)
    if empty:
        raise ValueError(f"не заполнен параметр пайплайна: {', '.join(empty)}")
    return values


def _next(transitions: list[Transition], node_id: str, outcome: str | None) -> str | None:
    """Куда идти после узла: переход со своим исходом, иначе переход «при любом исходе»."""
    moves = {move.when: move.target for move in transitions if move.source == node_id}
    return moves.get(outcome, moves.get(None))


def _with_params(value: Any, params: Mapping[str, Any]) -> Any:
    """Настройки узла, в которых ссылки `{"$param": "имя"}` заменены значениями."""
    if isinstance(value, dict):
        if set(value) == {"$param"}:
            return params[value["$param"]]
        return {key: _with_params(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [_with_params(item, params) for item in value]
    return value


def _inputs(node: BlockNode, manifest: Manifest, state: RunState) -> dict[str, Any]:
    """Значения входов узла: по каждой привязке — последнее значение указанного выхода."""
    values = {}
    for name, bound in node.inputs.items():
        source, port = _single_ref(bound)
        written = state.ports.get(source, {})
        if port in written:
            # Блок получает копию: правка входа на месте не меняет чужой выход в состоянии.
            values[name] = copy.deepcopy(written[port])
    missing = [port.name for port in manifest.inputs if port.required and port.name not in values]
    if missing:
        raise NodeFailed(f"обязательный вход остался без данных: {', '.join(missing)}")
    return values


def _single_ref(bound: Binding) -> tuple[str, str]:
    refs = bound if isinstance(bound, list) else [bound]
    if len(refs) > 1:
        raise NodeFailed(NOT_YET.format("выбирать из нескольких ссылок последнюю записанную"))
    source, port, *field = refs[0].split(".")
    if field:
        raise NodeFailed(NOT_YET.format("читать поле записи"))
    return source, port


def _checked_outputs(manifest: Manifest, result: Any) -> dict[str, Any]:
    """Выходы блока в виде JSON — после проверки, что результат не расходится с манифестом."""
    if not isinstance(result, Done | Waiting):
        raise NodeFailed(
            f"блок «{manifest.id}» вернул не результат `run()`, а {type(result).__name__}"
        )
    problems = result_problems(manifest, result)
    if not problems and isinstance(result, Waiting):
        problems = [NOT_YET.format("ставить запуск на паузу")]
    if problems:
        raise NodeFailed(f"блок «{manifest.id}»: " + "; ".join(problems))
    try:
        # В состоянии лежит только то, что можно записать в JSON (ADR 0007): так значение
        # одинаково выглядит до сохранения в базу и после чтения из неё.
        outputs = result.model_dump(mode="json")["outputs"]
    except Exception as error:
        raise NodeFailed(
            f"блок «{manifest.id}»: результат нельзя записать в JSON: {error}"
        ) from error
    for name, value in outputs.items():
        port = manifest.output(name)
        try:
            found = value_problems(port, value, port.json_schema)
        except Exception as error:
            # Например, схема выхода в манифесте ссылается на то, чего в ней нет.
            found = [f"значение не удалось сверить со схемой порта: {type(error).__name__}"]
        problems += [f"выход «{name}»: {text}" for text in found]
    if problems:
        raise NodeFailed(f"блок «{manifest.id}»: " + "; ".join(problems))
    return outputs
