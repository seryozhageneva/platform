"""Цикл с ограничителем: переход назад, на пути которого стоит узел со счётчиком.

Ограничитель говорит, сколько раз узел можно пройти, куда идти потом (`otherwise`) и на каком
узле счётчик обнуляется (`reset_on`). Пример из сценария 1: не больше трёх подсказок на задачу.
"""

import pytest

from backend.core.contracts.run import Done
from backend.core.contracts.state import RunStatus


def tick(node_id: str, **more) -> dict:
    return {"id": node_id, "type": "block", "block": "transform.fake_tick", **more}


@pytest.fixture(autouse=True)
def tick_block(add_block):
    """Блок без входов и выходов: тесты смотрят только на то, сколько раз он вызван."""

    async def run(inputs, config, context):
        return Done()

    add_block("transform.fake_tick", run)


def test_node_runs_no_more_than_max_times_then_goes_otherwise(go, graph, called):
    pipeline = graph(
        [tick("hint", limit={"max": 3, "otherwise": "after"}), tick("after")],
        [("hint", None, "hint")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["hint", "hint", "hint", "after"]
    assert state.counters == {"hint": 3}
    assert go.journal("limit_reached") == [("hint", "limit_reached", {"max": 3})]


def test_without_otherwise_the_branch_ends(go, graph, called):
    pipeline = graph([tick("hint", limit={"max": 2})], [("hint", None, "hint")])

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE and state.current == []
    assert called() == ["hint", "hint"]
    assert go.store.journal[-2:] == [
        ("hint", "limit_reached", {"max": 2}),
        ("hint", "run_done", {}),
    ]


def test_max_is_taken_from_a_pipeline_param(go, graph, called):
    pipeline = graph(
        [tick("hint", limit={"max": {"$param": "max_hints"}})],
        [("hint", None, "hint")],
        params=[{"name": "max_hints", "title": "Подсказок", "type": "integer", "default": 3}],
    )

    go.start(pipeline)
    assert called() == ["hint"] * 3

    go.start(pipeline, run_id="run-2", params={"max_hints": 1})
    assert called() == ["hint"] * 4


def test_counter_is_reset_on_the_given_node(go, graph, called):
    """Вложенные циклы, как в сценарии 1: две задачи, на каждую — не больше двух подсказок."""
    pipeline = graph(
        [
            tick("task", limit={"max": 2}),
            tick("hint", limit={"max": 2, "otherwise": "task", "reset_on": "task"}),
        ],
        [("task", None, "hint"), ("hint", None, "hint")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    # Без `reset_on` на вторую задачу подсказок бы не осталось.
    assert called() == ["task", "hint", "hint", "task", "hint", "hint"]


def test_counter_without_reset_is_one_for_the_whole_run(go, graph, called):
    pipeline = graph(
        [tick("task", limit={"max": 2}), tick("hint", limit={"max": 2, "otherwise": "task"})],
        [("task", None, "hint"), ("hint", None, "hint")],
    )

    go.start(pipeline)

    assert called() == ["task", "hint", "hint", "task"]


def test_counting_goes_on_after_a_server_restart(go, graph, called):
    """Счётчик лежит в состоянии запуска: после перезапуска узел не получает лишних попыток."""
    pipeline = graph(
        [tick("hint", limit={"max": 3, "otherwise": "after"}), tick("after")],
        [("hint", None, "hint")],
    )
    go.interrupted(current=["hint"], counters={"hint": 2})

    state = go.resume(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["hint", "after"]


def test_failed_node_does_not_spend_an_attempt(go, graph, add_block, called):
    failures = iter([True, False, False])

    async def answer(inputs, config, context):
        if next(failures):
            raise RuntimeError("модель недоступна")
        return Done()

    # Блок ждёт человека, поэтому движок его не повторяет: падение сразу останавливает запуск.
    add_block("student.fake_once", answer, kind="interactive", screen="answer_form")
    pipeline = graph(
        [{"id": "ask", "type": "block", "block": "student.fake_once", "limit": {"max": 2}}],
        [("ask", None, "ask")],
    )

    failed = go.start(pipeline)
    assert failed.status is RunStatus.ERROR and failed.counters == {}

    state = go.resume(pipeline)
    assert state.status is RunStatus.DONE
    # Упавший вызов в счёт не пошёл: после него узел выполнен ещё два раза.
    assert called() == ["ask", "ask", "ask"]
    assert state.counters == {"ask": 2}


def test_param_that_is_not_a_whole_number_stops_the_run(go, graph, called):
    pipeline = graph(
        [tick("hint", limit={"max": {"$param": "max_hints"}})],
        params=[{"name": "max_hints", "title": "Подсказок", "type": "integer", "default": 3}],
    )

    # Тип значения параметра при запуске проверяют валидатор и API (задачи 06 и 08).
    state = go.start(pipeline, params={"max_hints": "три"})

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «hint»: ограничитель: в параметре «max_hints» не целое число"
    assert called() == []
