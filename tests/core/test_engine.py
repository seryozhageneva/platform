"""Движок v1 на фейковых блоках: без базы и без ИИ-модели.

Хранилище здесь — словарь в памяти. То же самое с настоящей базой — в `test_engine_db.py`.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from backend.core.contracts.pipeline import parse_pipeline
from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.run import BlockEvent, Done, Waiting
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus, RunStore
from backend.core.contracts.wiring import check_wiring
from backend.core.engine import Engine, LoadedBlock

RUN = {"run_id": "run-1", "pipeline_id": "pipeline-1", "pipeline_version": 1}
EVENT = Event(trigger=TriggerType.MANUAL, occurred_at=datetime(2026, 10, 12, 9, 30, tzinfo=UTC))


def start(engine: Engine, pipeline, **more):
    return asyncio.run(engine.start(pipeline, **{**RUN, "event": EVENT, **more}))


def with_run(blocks, block_id, run):
    """Те же блоки, но у одного подменена функция `run`."""
    return {**blocks, block_id: LoadedBlock(blocks[block_id].manifest, run)}


def nodes_called(calls) -> list[str]:
    return [node for node, *_ in calls]


# --- Прямая цепочка ----------------------------------------------------------------------


def test_fake_pipeline_fits_the_contract(pipeline, blocks):
    manifests = {name: block.manifest for name, block in blocks.items()}
    assert check_wiring(pipeline, manifests) == []


def test_memory_store_implements_the_contract_interface(store):
    assert isinstance(store, RunStore)


def test_three_fake_blocks_reach_the_end(store, blocks, pipeline, calls):
    state = start(Engine(store, blocks), pipeline)

    assert state.status is RunStatus.DONE
    assert state.current == [] and state.error is None
    assert nodes_called(calls) == ["make", "upper", "keep"]
    assert state.ports["keep"]["report"] == {"text": "ПРИВЕТ", "length": 6}
    # В хранилище лежит то же состояние, что вернул движок.
    assert asyncio.run(store.load("run-1")) == state


def test_data_flows_along_bindings(store, blocks, pipeline, calls):
    state = start(Engine(store, blocks), pipeline)

    inputs = {node: given for node, given, *_ in calls}
    assert inputs["make"] == {}
    assert inputs["upper"] == {"text": {"text": "привет"}}
    assert inputs["keep"]["text"] == {"text": "ПРИВЕТ"}
    # Событие триггера — обычный выход: блок читает его по ссылке `start.event`.
    assert inputs["keep"]["event"] == state.ports["start"]["event"]
    assert inputs["keep"]["event"]["trigger"] == "manual"
    assert inputs["keep"]["event"]["occurred_at"] == "2026-10-12T09:30:00Z"


def test_params_are_put_into_config(store, blocks, pipeline, calls):
    by_default = start(Engine(store, blocks), pipeline)
    assert by_default.params == {"phrase": "привет"}
    assert calls[0][2] == {"text": "привет"}

    calls.clear()
    given = start(Engine(store, blocks), pipeline, run_id="run-2", params={"phrase": "логарифм"})
    assert given.params == {"phrase": "логарифм"}
    assert calls[0][2] == {"text": "логарифм"}
    assert given.ports["keep"]["report"]["text"] == "ЛОГАРИФМ"


def test_empty_param_stops_the_run_before_it_starts(store, blocks, pipeline_data, calls):
    del pipeline_data["params"][0]["default"]
    pipeline = parse_pipeline(pipeline_data)

    with pytest.raises(ValueError, match="не заполнен параметр пайплайна: phrase"):
        start(Engine(store, blocks), pipeline)
    with pytest.raises(ValueError, match="у пайплайна нет параметра: topic"):
        start(Engine(store, blocks), pipeline, params={"phrase": "а", "topic": "б"})
    assert store.saved == [] and calls == []


def test_block_gets_run_details_in_context(store, blocks, pipeline, calls):
    class Model:
        """Модель-заглушка: движок только передаёт её блоку и сам не вызывает."""

        async def complete(self, messages, *, schema=None, model=None):
            raise AssertionError("в этом тесте модель никто не вызывает")

    model = Model()
    start(Engine(store, blocks, llm=model), pipeline, student_id="student-1", teacher_id="t-1")

    context = calls[1][3]
    assert (context.run_id, context.node_id, context.pipeline_id) == (
        "run-1",
        "upper",
        "pipeline-1",
    )
    assert (context.student_id, context.teacher_id) == ("student-1", "t-1")
    assert context.params == {"phrase": "привет"}
    assert context.attempt == 1
    assert context.shown is None and context.human_response is None
    assert context.llm is model
    # MCP-инструменты в движке v1 блоку не выдаются.
    assert context.tools is None


def test_trigger_without_transitions_is_a_finished_run(store, blocks, pipeline_data, calls):
    pipeline_data["transitions"] = []
    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.DONE and calls == []
    assert [kind for _, kind, _ in store.journal] == ["run_started", "run_done"]


def test_block_cannot_change_the_outputs_of_other_nodes(store, blocks, pipeline):
    """Блок получает копии входов: правка на месте не доходит до состояния запуска."""

    async def upper_in_place(inputs, config, context):
        inputs["text"]["text"] = inputs["text"]["text"].upper()
        return Done(outputs={"text": inputs["text"]})

    blocks = with_run(blocks, "transform.fake_upper", upper_in_place)
    state = start(Engine(store, blocks), pipeline)

    assert state.ports["make"] == {"text": {"text": "привет"}}
    assert state.ports["upper"] == {"text": {"text": "ПРИВЕТ"}}
    assert asyncio.run(store.load("run-1")) == state


def test_run_cannot_be_started_twice(store, blocks, pipeline, calls):
    done = start(Engine(store, blocks), pipeline)

    with pytest.raises(ValueError, match="запуск «run-1» уже есть"):
        start(Engine(store, blocks), pipeline, params={"phrase": "другая"})

    # Первый запуск не затёрт, блоки второй раз не вызывались.
    assert asyncio.run(store.load("run-1")) == done
    assert nodes_called(calls) == ["make", "upper", "keep"]
    assert len(store.journal) == 7


# --- Сохранение состояния и журнал --------------------------------------------------------


def test_state_is_saved_after_every_node(store, blocks, pipeline):
    start(Engine(store, blocks), pipeline)

    assert [(saved.status, saved.current) for saved in store.saved] == [
        (RunStatus.RUNNING, ["make"]),
        (RunStatus.RUNNING, ["upper"]),
        (RunStatus.RUNNING, ["keep"]),
        (RunStatus.DONE, []),
    ]
    # Выходы копятся шаг за шагом: в каждом сохранении — всё, что уже получено.
    assert [sorted(saved.ports) for saved in store.saved] == [
        ["start"],
        ["make", "start"],
        ["make", "start", "upper"],
        ["keep", "make", "start", "upper"],
    ]


def test_journal_keeps_block_and_engine_events_in_order(store, blocks, pipeline):
    start(Engine(store, blocks), pipeline)

    assert store.journal == [
        ("start", "run_started", {"trigger": "manual"}),
        ("make", "text_made", {}),
        ("make", "node_done", {"outcome": "ok"}),
        ("upper", "node_done", {"outcome": "ok"}),
        ("keep", "text_kept", {"length": 6}),
        ("keep", "node_done", {"outcome": "ok"}),
        ("keep", "run_done", {}),
    ]


def test_values_in_state_are_json(store, blocks, pipeline):
    """Дата в выходе блока становится строкой сразу, а не только после записи в базу."""

    async def keep(inputs, config, context):
        return Done(outputs={"report": {"at": datetime(2026, 10, 12, 9, 30, tzinfo=UTC)}})

    state = start(Engine(store, with_run(blocks, "sink.fake_keep", keep)), pipeline)

    assert state.ports["keep"]["report"] == {"at": "2026-10-12T09:30:00Z"}
    assert asyncio.run(store.load("run-1")) == state


# --- Выбор перехода -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "transitions", "called"),
    [
        ("heads", [("coin", "heads", "left"), ("coin", None, "right")], ["left"]),
        # Для исхода `tails` своего перехода нет — срабатывает переход «при любом исходе».
        ("tails", [("coin", "heads", "left"), ("coin", None, "right")], ["right"]),
        # Подходящего перехода нет совсем — ветка заканчивается, запуск завершён.
        ("tails", [("coin", "heads", "left")], []),
    ],
    ids=["own_transition", "any_outcome_transition", "no_transition"],
)
def test_transition_is_chosen_by_outcome(
    store, blocks, manifest_for, calls, outcome, transitions, called
):
    async def coin(inputs, config, context):
        return Done(outcome=outcome)

    manifest = manifest_for("check.fake_coin", outcomes=["heads", "tails"])
    blocks = {**blocks, "check.fake_coin": LoadedBlock(manifest, coin)}
    text = {"type": "block", "block": "source.fake_text", "config": {"text": "а"}}
    pipeline = parse_pipeline(
        {
            "id": "coin_flip",
            "name": "Монетка",
            "nodes": [
                {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
                {"id": "coin", "type": "block", "block": "check.fake_coin"},
                {"id": "left", **text},
                {"id": "right", **text},
            ],
            "transitions": [
                {"from": "start", "to": "coin"},
                *(
                    {"from": source, "to": target} | ({"when": when} if when else {})
                    for source, when, target in transitions
                ),
            ],
        }
    )

    state = start(Engine(store, blocks), pipeline)

    assert state.status is RunStatus.DONE
    assert nodes_called(calls) == called


# --- Ошибки -------------------------------------------------------------------------------


def test_failed_block_stops_the_run(store, blocks, pipeline, calls):
    async def broken(inputs, config, context):
        raise RuntimeError("модель недоступна")

    state = start(Engine(store, with_run(blocks, "transform.fake_upper", broken)), pipeline)

    reason = "блок «transform.fake_upper» упал: RuntimeError: модель недоступна"
    assert state.status is RunStatus.ERROR
    assert state.error == f"узел «upper»: {reason}"
    # Запуск стоит на упавшем узле; то, что получено до него, не потеряно.
    assert state.current == ["upper"]
    assert state.ports["make"] == {"text": {"text": "привет"}}
    assert nodes_called(calls) == ["make"]
    assert store.journal[-1] == ("upper", "node_failed", {"error": reason})
    assert asyncio.run(store.load("run-1")) == state


def test_run_continues_from_the_failed_node_with_a_new_engine(store, blocks, pipeline, calls):
    async def broken(inputs, config, context):
        raise RuntimeError("модель недоступна")

    failed = start(Engine(store, with_run(blocks, "transform.fake_upper", broken)), pipeline)
    assert failed.status is RunStatus.ERROR

    # Новый движок знает о запуске только то, что лежит в хранилище.
    state = asyncio.run(Engine(store, blocks).resume(pipeline, "run-1"))

    assert state.status is RunStatus.DONE and state.error is None
    assert state.ports["keep"]["report"] == {"text": "ПРИВЕТ", "length": 6}
    # Первый блок второй раз не вызывался.
    assert nodes_called(calls) == ["make", "upper", "keep"]


def test_run_continues_after_a_server_restart(store, blocks, pipeline, calls):
    """Сервер упал посреди запуска: в хранилище остался статус «выполняется»."""
    interrupted = RunState(
        **RUN,
        status=RunStatus.RUNNING,
        params={"phrase": "привет"},
        current=["upper"],
        ports={"make": {"text": {"text": "привет"}}},
    )
    asyncio.run(store.save(interrupted))

    state = asyncio.run(Engine(store, blocks).resume(pipeline, "run-1"))

    assert state.status is RunStatus.DONE
    assert state.ports["keep"]["report"] == {"text": "ПРИВЕТ", "length": 6}
    assert nodes_called(calls) == ["upper", "keep"]


def test_state_that_cannot_be_saved_stops_the_run(store, blocks, pipeline, calls):
    """Хранилище не приняло выход блока — запуск не остаётся «выполняться» навсегда."""
    save = store.save

    async def picky_save(state):
        # Как PostgreSQL: текст с нулевым символом в JSON-поле не записывается.
        if "\\u0000" in state.model_dump_json():
            raise RuntimeError("хранилище не записывает нулевой символ; пароль: secret")
        await save(state)

    store.save = picky_save

    async def with_zero(inputs, config, context):
        return Done(outputs={"text": {"text": "при\x00вет"}})

    state = start(Engine(store, with_run(blocks, "transform.fake_upper", with_zero)), pipeline)

    assert state.status is RunStatus.ERROR
    # В тексте ошибки — только вид сбоя: сообщение хранилища может нести данные запуска.
    assert state.error == ("узел «upper»: не удалось сохранить состояние после узла (RuntimeError)")
    # Шаг отменён: запуск стоит на этом узле, его выходов в состоянии нет.
    assert state.current == ["upper"] and "upper" not in state.ports
    assert state.ports["make"] == {"text": {"text": "привет"}}
    assert asyncio.run(store.load("run-1")) == state
    assert store.journal[-1][:2] == ("upper", "node_failed")

    done = asyncio.run(Engine(store, blocks).resume(pipeline, "run-1"))
    assert done.status is RunStatus.DONE
    assert nodes_called(calls) == ["make", "upper", "keep"]


def test_error_text_the_store_rejects_is_cleaned(strict_store, blocks, pipeline):
    """Блок процитировал в ошибке текст с нулевым символом: статус «ошибка» всё равно сохранён."""

    async def broken(inputs, config, context):
        raise ValueError("не разобрать текст: при\x00вет и \ud800")

    blocks = with_run(blocks, "transform.fake_upper", broken)
    state = start(Engine(strict_store, blocks), pipeline)

    reason = "блок «transform.fake_upper» упал: ValueError: не разобрать текст: при\ufffdвет и ?"
    assert state.status is RunStatus.ERROR
    assert state.error == f"узел «upper»: {reason}"
    assert asyncio.run(strict_store.load("run-1")) == state
    assert strict_store.journal[-1] == ("upper", "node_failed", {"error": reason})


def test_error_text_that_cannot_be_saved_is_replaced_by_a_short_one(store, blocks, pipeline):
    save = store.save

    async def picky_save(state):
        if state.error and "модель недоступна" in state.error:
            raise RuntimeError("хранилище не приняло текст ошибки")
        await save(state)

    store.save = picky_save

    async def broken(inputs, config, context):
        raise RuntimeError("модель недоступна")

    state = start(Engine(store, with_run(blocks, "transform.fake_upper", broken)), pipeline)

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «upper»: текст ошибки не удалось сохранить (RuntimeError)"
    assert state.current == ["upper"]
    assert asyncio.run(store.load("run-1")) == state


@pytest.mark.parametrize("node", ["make", "keep"], ids=["middle_node", "last_node"])
def test_block_events_the_store_rejects_do_not_break_the_run(strict_store, blocks, pipeline, node):
    """Журнал не принял событие блока: шаг уже сохранён, запуск идёт дальше, потеря отмечена."""
    block_id = {"make": "source.fake_text", "keep": "sink.fake_keep"}[node]
    run = blocks[block_id].run

    async def with_bad_event(inputs, config, context):
        done = await run(inputs, config, context)
        return done.model_copy(update={"events": [BlockEvent(type="note", data={"t": "\x00"})]})

    state = start(Engine(strict_store, with_run(blocks, block_id, with_bad_event)), pipeline)

    assert state.status is RunStatus.DONE
    assert asyncio.run(strict_store.load("run-1")) == state
    kinds = [(at, kind) for at, kind, _ in strict_store.journal]
    assert (node, "note") not in kinds
    lost = kinds.index((node, "events_lost"))
    assert strict_store.journal[lost][2] == {"count": 1, "reason": "RuntimeError"}
    assert kinds[lost + 1] == (node, "node_done")
    assert kinds[-1] == ("keep", "run_done")


def test_finished_run_is_not_executed_again(store, blocks, pipeline, calls):
    done = start(Engine(store, blocks), pipeline)

    again = asyncio.run(Engine(store, blocks).resume(pipeline, "run-1"))

    assert again == done
    assert nodes_called(calls) == ["make", "upper", "keep"]


def test_unknown_run_cannot_be_continued(store, blocks, pipeline):
    with pytest.raises(LookupError, match="запуск «run-404» не найден"):
        asyncio.run(Engine(store, blocks).resume(pipeline, "run-404"))


# Значение, которое ссылается само на себя: в JSON такое не записать.
LOOP: dict = {}
LOOP["again"] = LOOP


@pytest.mark.parametrize(
    ("result", "problem"),
    [
        (Done(outcome="maybe"), "исход «maybe» не объявлен в манифесте"),
        (Done(outputs={"extra": 1}), "выход «extra» не объявлен в манифесте"),
        (Done(outputs={"text": {"words": 3}}), "выход «text»: text: обязательное поле"),
        (Done(outputs={"text": object()}), "результат нельзя записать в JSON"),
        (Done(outputs={"text": LOOP}), "результат нельзя записать в JSON"),
        (Done(events=[BlockEvent(type="made", data={"by": object()})]), "нельзя записать в JSON"),
        ({"text": "привет"}, "вернул не результат `run()`, а dict"),
    ],
    ids=[
        "undeclared_outcome",
        "undeclared_output",
        "wrong_value",
        "not_json",
        "refers_to_itself",
        "event_not_json",
        "not_a_result",
    ],
)
def test_block_that_breaks_its_manifest_stops_the_run(
    store, blocks, pipeline, calls, result, problem
):
    async def wrong(inputs, config, context):
        return result

    state = start(Engine(store, with_run(blocks, "transform.fake_upper", wrong)), pipeline)

    assert state.status is RunStatus.ERROR
    assert state.error.startswith("узел «upper»: блок «transform.fake_upper»")
    assert problem in state.error
    # Негодный результат в состояние не попал, следующий блок не вызван.
    assert "upper" not in state.ports
    assert nodes_called(calls) == ["make"]


def test_broken_port_schema_stops_the_run(store, blocks, manifest_for, pipeline):
    """Схема выхода в манифесте ссылается на то, чего в ней нет: сверить значение нечем."""
    report = {"name": "report", "title": "Отчёт", "type": "Data", "of": "report"}
    manifest = manifest_for(
        "sink.fake_keep",
        inputs=[{"name": "text", "title": "Текст", "type": "Text"}],
        outputs=[{**report, "schema": {"$ref": "#/$defs/missing"}}],
    )
    blocks = {**blocks, "sink.fake_keep": LoadedBlock(manifest, blocks["sink.fake_keep"].run)}

    state = start(Engine(store, blocks), pipeline)

    assert state.status is RunStatus.ERROR
    assert "выход «report»: значение не удалось сверить со схемой порта" in state.error
    assert state.current == ["keep"] and "keep" not in state.ports


def test_required_input_without_data_stops_the_run(store, blocks, pipeline_data, calls):
    # «upper» идёт сразу после триггера: выхода `make.text` к этому моменту ещё нет.
    pipeline_data["transitions"] = [{"from": "start", "to": "upper"}]
    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «upper»: обязательный вход остался без данных: text"
    assert calls == []


def test_optional_input_without_data_is_left_out(store, blocks, pipeline_data, calls):
    pipeline_data["nodes"][3]["inputs"]["event"] = "make.nothing"
    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.DONE
    assert calls[2][1] == {"text": {"text": "ПРИВЕТ"}}


def test_unknown_block_stops_the_run(store, blocks, pipeline_data):
    pipeline_data["nodes"][2]["block"] = "transform.missing"
    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «upper»: блок «transform.missing» не найден"


# --- То, что появится в задаче 05 ---------------------------------------------------------

INNER = {"id": "inner", "type": "block", "block": "transform.fake_upper"}


@pytest.mark.parametrize(
    ("change", "what"),
    [
        ({"type": "switch", "value": "make.text", "field": "text"}, "выполнять развилку"),
        (
            {"type": "for_each", "over": "make.text", "body": {"start": "inner", "nodes": [INNER]}},
            "выполнять «для каждого»",
        ),
        ({"limit": {"max": 2}}, "считать ограничитель"),
        ({"inputs": {"text": ["make.text", "start.event"]}}, "выбирать из нескольких ссылок"),
        ({"inputs": {"text": "make.text.text"}}, "читать поле записи"),
    ],
    ids=["switch", "for_each", "limit", "several_refs", "record_field"],
)
def test_constructs_of_task_05_stop_the_run_with_an_explanation(
    store, blocks, pipeline_data, calls, change, what
):
    node = {**pipeline_data["nodes"][2], **change}
    if node["type"] != "block":
        node = {"id": "upper", **change}
    pipeline_data["nodes"][2] = node

    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.ERROR
    assert state.error.startswith(f"узел «upper»: движок пока не умеет {what}")
    assert state.error.endswith("это появится в задаче 05")
    assert nodes_called(calls) == ["make"]


def test_block_that_waits_for_a_person_stops_the_run_with_an_explanation(
    store, blocks, manifest_for, pipeline_data
):
    async def ask(inputs, config, context):
        return Waiting(
            screen=ScreenType.ANSWER_FORM,
            data={"task_id": "t1", "statement": "Вычислите $2^3$.", "forms": ["text"]},
        )

    manifest = manifest_for("student.fake_ask", kind="interactive", screen="answer_form")
    blocks = {**blocks, "student.fake_ask": LoadedBlock(manifest, ask)}
    pipeline_data["nodes"][2] = {"id": "upper", "type": "block", "block": "student.fake_ask"}

    state = start(Engine(store, blocks), parse_pipeline(pipeline_data))

    assert state.status is RunStatus.ERROR
    assert "движок пока не умеет ставить запуск на паузу" in state.error
    assert state.waiting == []
