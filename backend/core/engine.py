"""Движок v2: выполняет пайплайн узел за узлом и после каждого узла сохраняет состояние.

Умеет всё, что есть в формате пайплайна: цепочку блоков, развилку, цикл с ограничителем,
паузу на человеке и «для каждого»; упавший автоматический блок повторяет. Решения — ADR 0008
(шаг, сохранение, ошибки) и ADR 0010 (всё остальное).

Движок знает только контракты (правило 4): хранилище, блоки и пайплайн ему передают снаружи.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.core.contracts.interfaces import LLMClient
from backend.core.contracts.manifest import Kind, Manifest
from backend.core.contracts.pipeline import (
    BlockNode,
    ForEachNode,
    ParamRef,
    Pipeline,
    SwitchNode,
    Transition,
    TriggerNode,
)
from backend.core.contracts.ports import Event, value_problems
from backend.core.contracts.run import (
    BlockEvent,
    BlockRun,
    Done,
    RunContext,
    Waiting,
    response_problems,
    result_problems,
)
from backend.core.contracts.state import RunState, RunStatus, RunStore, WaitingFor
from backend.core.data_flow import (
    MISSING,
    body_ids,
    forget,
    forget_output,
    read_binding,
    read_ref,
    with_params,
)

# Сколько раз подряд повторяется упавший автоматический блок (допущение 6 в docs/vision.md).
MAX_RETRIES = 3

# Запись для журнала: узел, события блока и следом — события самого движка.
Note = tuple[str, list[BlockEvent], list[BlockEvent]]


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


class ResponseRejected(ValueError):
    """Ответ человека не принят: запуск его не ждёт или ответ не подходит экрану.

    Состояние запуска при этом не меняется — человек может ответить ещё раз.
    """


@dataclass(frozen=True)
class _Place:
    """Где узел стоит в пайплайне."""

    node: Any
    # «Для каждого», в теле которого стоит узел; None — узел верхнего уровня.
    parent: str | None
    # Переходы того же уровня: из тела «для каждого» наружу переходов нет.
    transitions: list[Transition]


def _places(pipeline: Pipeline) -> dict[str, _Place]:
    places = {}

    def visit(nodes: list[Any], transitions: list[Transition], parent: str | None) -> None:
        for node in nodes:
            places[node.id] = _Place(node, parent, transitions)
            if isinstance(node, ForEachNode):
                visit(node.body.nodes, node.body.transitions, node.id)

    visit(pipeline.nodes, pipeline.transitions, None)
    return places


class _Step:
    """Один шаг над состоянием запуска: что записать и куда перейти.

    Блоков и хранилища не касается — это делает `Engine`. Записи для журнала копятся в
    `notes`: в журнал они попадут, только когда состояние после шага сохранено.
    """

    def __init__(self, places: Mapping[str, _Place], state: RunState) -> None:
        self.places = places
        self.state = state
        self.notes: list[Note] = []

    def note(self, node_id: str, kind: str, **data: Any) -> None:
        self.notes.append((node_id, [], [BlockEvent(type=kind, data=data)]))

    def finish(
        self,
        node_id: str,
        outputs: Mapping[str, Any],
        outcome: str,
        block_events: list[BlockEvent] | None = None,
    ) -> None:
        """Узел отработал: записать выходы, посчитать ограничители, выбрать переход."""
        state, place = self.state, self.places[node_id]
        if outputs:
            state.write(node_id, outputs)
        # Счётчик растёт только здесь: упавший узел и узел на паузе попытку не тратят.
        if place.node.limit is not None:
            state.counters[node_id] = state.counters.get(node_id, 0) + 1
        for other in self.places.values():
            limit = getattr(other.node, "limit", None)
            if limit is not None and limit.reset_on == node_id:
                state.counters.pop(other.node.id, None)
        done = BlockEvent(type="node_done", data={"outcome": outcome})
        self.notes.append((node_id, block_events or [], [done]))
        self.go(node_id, _next(place.transitions, node_id, outcome))

    def go(self, node_id: str, target: str | None) -> None:
        """После узла `node_id` идти к `target`; None — ветка на этом закончилась."""
        place = self.places[node_id]
        if target is not None:
            self.state.current = [target]
        elif place.parent is not None:
            # Ветка внутри тела «для каждого» — закончился один элемент, а не запуск.
            self._end_item(place.parent)
        else:
            self.state.current, self.state.status = [], RunStatus.DONE
            self.note(node_id, "run_done")

    def limit_reached(self, node: Any) -> bool:
        """Ограничитель: узел уже пройден `max` раз — вместо него идём на `otherwise`."""
        limit = node.limit
        if limit is None:
            return False
        allowed = limit.max
        if isinstance(allowed, ParamRef):
            allowed = self.state.params.get(allowed.param)
            if not isinstance(allowed, int) or isinstance(allowed, bool):
                raise NodeFailed(f"ограничитель: в параметре «{limit.max.param}» не целое число")
        if self.state.counters.get(node.id, 0) < allowed:
            return False
        self.note(node.id, "limit_reached", max=allowed)
        self.go(node.id, limit.otherwise)
        return True

    def switch(self, node: SwitchNode) -> None:
        """Развилка: исход узла — значение поля у данных."""
        value = read_ref(self.state, node.value)
        if value is MISSING:
            raise NodeFailed(f"развилка: по ссылке «{node.value}» нет данных")
        chosen = value.get(node.field) if isinstance(value, dict) else None
        if isinstance(chosen, bool):
            outcome = "true" if chosen else "false"
        elif isinstance(chosen, str | int):
            outcome = str(chosen)
        else:
            raise NodeFailed(
                f"развилка: у данных «{node.value}» нет значения в поле «{node.field}»"
            )
        self.finish(node.id, {}, outcome)

    def enter_for_each(self, node: ForEachNode) -> None:
        """«Для каждого»: начать с первого элемента; пустой список — исход `empty`."""
        items = self._items(node)
        if node.collect is not None:
            # Собранное начинается заново: в цикле узел может выполняться не в первый раз.
            self.state.write(node.id, {"results": []})
        if items:
            self._start_item(node, items, 0)
        else:
            self.finish(node.id, {}, "empty")

    def _items(self, node: ForEachNode) -> list[Any]:
        items = read_ref(self.state, node.over)
        if not isinstance(items, list):
            raise NodeFailed(f"«для каждого»: по ссылке «{node.over}» нет списка")
        return items

    def _start_item(self, node: ForEachNode, items: list[Any], index: int) -> None:
        # Тело очищается перед каждым элементом: иначе собрать можно было бы чужое значение.
        forget(self.state, body_ids(node))
        self.state.item_index[node.id] = index
        self.state.write(node.id, {"item": items[index]})
        self.state.current = [node.body.start]
        self.note(node.id, "item_started", index=index)

    def _end_item(self, node_id: str) -> None:
        """Ветка элемента закончилась: собрать `collect` и взять следующий элемент."""
        node, state = self.places[node_id].node, self.state
        index = state.item_index.get(node_id)
        if index is None:
            raise NodeFailed(f"«для каждого» «{node_id}»: в состоянии нет номера элемента")
        self._collect(node, index)
        items = self._items(node)
        if index + 1 < len(items):
            self._start_item(node, items, index + 1)
            return
        # Список пройден. `item` и значения тела видны только внутри — снаружи их нет.
        forget(state, body_ids(node))
        forget_output(state, node_id, "item")
        del state.item_index[node_id]
        self.finish(node_id, {}, "ok")

    def _collect(self, node: ForEachNode, index: int) -> None:
        if node.collect is None:
            return
        if isinstance(node.collect, str):
            value = read_ref(self.state, node.collect)
            missing = [node.collect] if value is MISSING else []
        else:
            value = {name: read_binding(self.state, bound) for name, bound in node.collect.items()}
            missing = [name for name, found in value.items() if found is MISSING]
        if missing:
            # Ветка элемента не дошла до узла, с которого собирают: элемент пропускается.
            self.note(node.id, "item_skipped", index=index, missing=missing)
            return
        results = self.state.ports[node.id].get("results", [])
        self.state.write(node.id, {"results": [*results, value]})
        self.note(node.id, "item_collected", index=index)


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
        # Законченный запуск продолжать некуда, а запуск на паузе продолжает `respond`.
        if state.status in (RunStatus.DONE, RunStatus.WAITING):
            return state
        state.error = None
        if state.waiting:
            # Блок упал уже после ответа человека. Экран остаётся прежним: человек отвечает
            # ещё раз, а блок не вызывается заново без него.
            state.status = RunStatus.WAITING
            await self._store.save(state)
            return state
        state.status = RunStatus.RUNNING
        return await self._advance(pipeline, state)

    async def respond(
        self, pipeline: Pipeline, run_id: str, node_id: str, response: Mapping[str, Any]
    ) -> RunState:
        """Передаёт ответ человека узлу, на котором запуск стоит на паузе, и идёт дальше.

        Блок вызывается второй раз с теми же входами; в `context.shown` — данные экрана,
        которые он сам просил показать, в `context.human_response` — ответ.
        """
        state = await self._store.load(run_id)
        if state is None:
            raise LookupError(f"запуск «{run_id}» не найден")
        waiting = next((item for item in state.waiting if item.node_id == node_id), None)
        if state.status is not RunStatus.WAITING or waiting is None:
            raise ResponseRejected(f"запуск «{run_id}» не ждёт ответа на узле «{node_id}»")
        problems = response_problems(waiting.screen, dict(response))
        if problems:
            raise ResponseRejected(
                f"ответ не подходит экрану «{waiting.screen.value}»: " + "; ".join(problems)
            )
        state.status = RunStatus.RUNNING
        return await self._advance(pipeline, state, copy.deepcopy(dict(response)))

    async def _advance(
        self, pipeline: Pipeline, state: RunState, response: dict[str, Any] | None = None
    ) -> RunState:
        """Выполняет узлы, пока запуск не закончится, не встанет на паузу или не упадёт.

        `response` — ответ человека для первого из узлов: с него запуск снимается с паузы.
        """
        places = _places(pipeline)
        while state.status is RunStatus.RUNNING and state.current:
            node_id = state.current[0]
            # Копия на случай отмены шага: с ней запуск остаётся на этом узле без следов
            # незаконченного шага — выходов, счётчиков, собранных элементов.
            before = state.model_copy(deep=True)
            step = _Step(places, state)
            try:
                await self._step(step, node_id, response)
            except NodeFailed as failure:
                return await self._fail(before, node_id, str(failure))
            response = None
            try:
                # Состояние сохраняется после каждого узла: при сбое теряется не больше шага.
                await self._store.save(state)
            except Exception as error:
                # Хранилище не приняло состояние — например, в выходе блока оказался символ,
                # который база не записывает. Шаг отменяется. Текст ошибки хранилища в
                # состояние не идёт: в нём могут быть данные запуска.
                reason = f"не удалось сохранить состояние после узла ({type(error).__name__})"
                return await self._fail(before, node_id, reason)
            for at, block_events, own_events in step.notes:
                await self._journal(state.run_id, at, block_events, own_events)
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

    async def _step(self, step: _Step, node_id: str, response: dict[str, Any] | None) -> None:
        """Один шаг: выполняет узел и меняет состояние в `step`. В хранилище не пишет."""
        place = step.places.get(node_id)
        if place is None:
            raise NodeFailed("такого узла нет в пайплайне")
        node = place.node
        if isinstance(node, TriggerNode):
            raise NodeFailed("узел-триггер не выполняется: с него запуск только начинается")
        if step.limit_reached(node):
            return
        if isinstance(node, SwitchNode):
            step.switch(node)
        elif isinstance(node, ForEachNode):
            step.enter_for_each(node)
        else:
            await self._run_block(step, node, response)

    async def _run_block(
        self, step: _Step, node: BlockNode, response: dict[str, Any] | None
    ) -> None:
        state = step.state
        block = self._blocks.get(node.block)
        if block is None:
            raise NodeFailed(f"блок «{node.block}» не найден")
        result = await self._call(node, block, state, response)
        checked = _checked(block.manifest, result)
        if response is not None:
            step.note(node.id, "node_resumed")
        if isinstance(result, Waiting):
            who = "teacher" if block.manifest.kind is Kind.APPROVAL else "student"
            state.status = RunStatus.WAITING
            state.waiting = [
                WaitingFor(node_id=node.id, who=who, screen=result.screen, data=checked["data"])
            ]
            asked = BlockEvent(
                type="node_waiting", data={"screen": result.screen.value, "who": who}
            )
            step.notes.append((node.id, result.events, [asked]))
            return
        state.waiting = []
        step.finish(node.id, checked["outputs"], result.outcome, result.events)

    async def _call(
        self, node: BlockNode, block: LoadedBlock, state: RunState, response: dict[str, Any] | None
    ) -> Any:
        """Вызывает блок. Упавший автоматический блок вызывается снова — до `MAX_RETRIES` раз."""
        inputs = _inputs(node, block.manifest, state)
        config = with_params(node.config, state.params)
        # Блок, который ждёт человека, не повторяется: после ответа повтор задал бы ему
        # тот же вопрос без самого человека.
        retries = MAX_RETRIES if block.manifest.kind is Kind.AUTO else 0
        for attempt in range(1, retries + 2):
            context = RunContext(
                run_id=state.run_id,
                node_id=node.id,
                pipeline_id=state.pipeline_id,
                params=state.params,
                student_id=state.student_id,
                teacher_id=state.teacher_id,
                attempt=attempt,
                shown=state.waiting[0].data if response is not None else None,
                human_response=response,
                llm=self._llm,
            )
            try:
                # Каждая попытка получает свои копии: блок мог успеть поправить входы на месте.
                return await block.run(copy.deepcopy(inputs), copy.deepcopy(config), context)
            except Exception as error:
                reason = f"блок «{node.block}» упал: {type(error).__name__}: {error}"
                if attempt > retries:
                    raise NodeFailed(reason) from error
                failed = BlockEvent(
                    type="attempt_failed", data={"attempt": attempt, "error": _storable(reason)}
                )
                await self._journal(state.run_id, node.id, [], [failed])
        raise AssertionError("цикл попыток всегда заканчивается результатом или ошибкой")


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


def _inputs(node: BlockNode, manifest: Manifest, state: RunState) -> dict[str, Any]:
    """Значения входов узла: по каждой привязке — последнее значение указанного выхода."""
    values = {}
    for name, bound in node.inputs.items():
        value = read_binding(state, bound)
        if value is not MISSING:
            values[name] = value
    missing = [port.name for port in manifest.inputs if port.required and port.name not in values]
    if missing:
        raise NodeFailed(f"обязательный вход остался без данных: {', '.join(missing)}")
    return values


def _checked(manifest: Manifest, result: Any) -> dict[str, Any]:
    """Результат блока в виде JSON — после проверки, что он не расходится с манифестом."""
    if not isinstance(result, Done | Waiting):
        raise NodeFailed(
            f"блок «{manifest.id}» вернул не результат `run()`, а {type(result).__name__}"
        )
    problems = result_problems(manifest, result)
    if problems:
        raise NodeFailed(f"блок «{manifest.id}»: " + "; ".join(problems))
    try:
        # В состоянии лежит только то, что можно записать в JSON (ADR 0007): так значение
        # одинаково выглядит до сохранения в базу и после чтения из неё.
        checked = result.model_dump(mode="json")
    except Exception as error:
        raise NodeFailed(
            f"блок «{manifest.id}»: результат нельзя записать в JSON: {error}"
        ) from error
    if isinstance(result, Waiting):
        return checked
    for name, value in checked["outputs"].items():
        port = manifest.output(name)
        try:
            found = value_problems(port, value, port.json_schema)
        except Exception as error:
            # Например, схема выхода в манифесте ссылается на то, чего в ней нет.
            found = [f"значение не удалось сверить со схемой порта: {type(error).__name__}"]
        problems += [f"выход «{name}»: {text}" for text in found]
    if problems:
        raise NodeFailed(f"блок «{manifest.id}»: " + "; ".join(problems))
    return checked
