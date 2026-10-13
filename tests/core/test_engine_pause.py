"""Пауза: блок ждёт человека, запуск сохраняется и продолжается после ответа.

Обмен идёт в два вызова одной функции `run()` (ADR 0004): первый возвращает «жду человека»,
второй получает ответ и возвращает «готово». Между ними сервер можно перезапустить.
"""

import asyncio

import pytest

from backend.core.contracts.run import BlockEvent, Done, Waiting
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunStatus, WaitingFor
from backend.core.engine import ResponseRejected

QUESTION = {"task_id": "t1", "statement": "Вычислите $2^3$.", "forms": ["text"]}
ASK = {"id": "ask", "type": "block", "block": "student.fake_ask", "inputs": {"text": "make.text"}}
MAKE = {"id": "make", "type": "block", "block": "source.fake_text", "config": {"text": "2^3"}}
CHECK = {
    "id": "check",
    "type": "block",
    "block": "check.fake_exact",
    "inputs": {"answer": "ask.answer"},
}


@pytest.fixture
def lesson(graph, ask, add_block):
    """Пайплайн «сделать текст → спросить ученика → проверить ответ»."""

    async def check(inputs, config, context):
        correct = inputs["answer"]["text"] == "8"
        return Done(
            outputs={"verdict": {"correct": correct}}, outcome="correct" if correct else "wrong"
        )

    add_block(
        "check.fake_exact",
        check,
        inputs=[{"name": "answer", "title": "Ответ", "type": "Answer"}],
        outputs=[{"name": "verdict", "title": "Вердикт", "type": "Verdict"}],
        outcomes=["correct", "wrong"],
    )
    return graph([MAKE, ASK, CHECK], [("make", None, "ask"), ("ask", "answer", "check")])


def test_run_pauses_and_is_saved(go, lesson, called):
    state = go.start(lesson)

    assert state.status is RunStatus.WAITING
    assert state.current == ["ask"]
    assert state.waiting == [
        WaitingFor(node_id="ask", who="student", screen=ScreenType.ANSWER_FORM, data=QUESTION)
    ]
    # Блок ещё не отработал: выходов у него нет, следующий узел не вызван.
    assert "ask" not in state.ports and called() == ["make", "ask"]
    assert go.store.journal[-1] == (
        "ask",
        "node_waiting",
        {"screen": "answer_form", "who": "student"},
    )
    assert asyncio.run(go.store.load("run-1")) == state


def test_approval_block_waits_for_the_teacher(go, graph, add_block):
    table = {"columns": [{"key": "text", "title": "Текст"}], "rows": [{"text": "а"}]}

    async def review(inputs, config, context):
        if context.human_response is None:
            return Waiting(
                screen=ScreenType.REVIEW_TABLE, data=table, events=[BlockEvent(type="table_built")]
            )
        return Done(outcome="approved")

    add_block(
        "approval.fake_review",
        review,
        kind="approval",
        screen="review_table",
        outcomes=["approved", "rejected"],
    )
    pipeline = graph([{"id": "review", "type": "block", "block": "approval.fake_review"}])

    state = go.start(pipeline)

    assert state.status is RunStatus.WAITING
    assert (state.waiting[0].who, state.waiting[0].screen) == ("teacher", ScreenType.REVIEW_TABLE)
    # События блока, который встал на паузу, тоже попадают в журнал.
    assert [kind for _, kind, _ in go.store.journal[-2:]] == ["table_built", "node_waiting"]

    done = go.respond(pipeline, "review", {"rows": [{"index": 0, "keep": True}]})
    assert done.status is RunStatus.DONE and done.waiting == []


def test_response_goes_to_the_same_block_and_the_run_continues(go, lesson, calls, answer_with):
    go.start(lesson)

    state = go.respond(lesson, "ask", answer_with("8"))

    assert state.status is RunStatus.DONE and state.waiting == []
    assert state.ports["ask"]["answer"] == {
        "task_id": "t1",
        "form": "text",
        "text": "8",
    }
    assert state.ports["check"]["verdict"]["correct"] is True
    first, second = (call for call in calls if call[0] == "ask")
    # Второй вызов — с теми же входами и настройками, что и первый.
    assert first[1] == second[1] == {"text": {"text": "2^3"}}
    assert first[3].shown is None and first[3].human_response is None
    assert second[3].shown == QUESTION
    assert second[3].human_response == answer_with("8")
    assert go.journal("node_resumed", "node_done")[-3:] == [
        ("ask", "node_resumed", {}),
        ("ask", "node_done", {"outcome": "answer"}),
        ("check", "node_done", {"outcome": "correct"}),
    ]
    assert asyncio.run(go.store.load("run-1")) == state


def test_response_that_does_not_fit_the_screen_is_rejected(go, lesson, called):
    waiting = go.start(lesson)

    # Действие «ответить» без самого ответа.
    with pytest.raises(ResponseRejected, match="ответ не подходит экрану «answer_form»"):
        go.respond(lesson, "ask", {"action": "answer"})
    with pytest.raises(ResponseRejected, match="неизвестное поле"):
        go.respond(lesson, "ask", {"action": "hint", "chat": "скажи ответ"})

    # Запуск по-прежнему ждёт: блок второй раз не вызывался, состояние то же.
    assert asyncio.run(go.store.load("run-1")) == waiting
    assert called() == ["make", "ask"]


def test_response_nobody_waits_for_is_rejected(go, lesson, called, answer_with):
    with pytest.raises(LookupError, match="запуск «run-1» не найден"):
        go.respond(lesson, "ask", answer_with("8"))

    go.start(lesson)
    with pytest.raises(ResponseRejected, match="не ждёт ответа на узле «check»"):
        go.respond(lesson, "check", answer_with("8"))

    done = go.respond(lesson, "ask", answer_with("8"))
    # Тот же ответ пришёл второй раз — например, ученик дважды нажал кнопку.
    with pytest.raises(ResponseRejected, match="не ждёт ответа на узле «ask»"):
        go.respond(lesson, "ask", answer_with("8"))

    assert asyncio.run(go.store.load("run-1")) == done
    assert called() == ["make", "ask", "ask", "check"]


def test_resume_does_not_call_the_block_that_waits(go, lesson, called):
    waiting = go.start(lesson)

    assert go.resume(lesson) == waiting
    assert called() == ["make", "ask"]


def test_block_may_ask_again(go, graph, add_block, answer_with, calls):
    again = {**QUESTION, "statement": "Ответ пуст. Вычислите $2^3$."}

    async def ask(inputs, config, context):
        if context.human_response is None:
            return Waiting(screen=ScreenType.ANSWER_FORM, data=QUESTION)
        if not context.human_response["answer"]["text"].strip():
            return Waiting(screen=ScreenType.ANSWER_FORM, data=again)
        return Done(outputs={"answer": context.human_response["answer"]})

    add_block(
        "student.fake_strict",
        ask,
        kind="interactive",
        screen="answer_form",
        outputs=[{"name": "answer", "title": "Ответ", "type": "Answer"}],
    )
    pipeline = graph([{"id": "ask", "type": "block", "block": "student.fake_strict"}])
    go.start(pipeline)

    state = go.respond(pipeline, "ask", answer_with(" "))
    assert state.status is RunStatus.WAITING
    assert state.waiting[0].data == again and "ask" not in state.ports

    state = go.respond(pipeline, "ask", answer_with("8"))
    assert state.status is RunStatus.DONE
    # При третьем вызове блок видит тот экран, который показан сейчас, а не первый.
    assert calls[2][3].shown == again


def test_block_that_fails_after_the_response_shows_the_screen_again(
    go, graph, add_block, answer_with, called
):
    broken = {"on": True}

    async def ask(inputs, config, context):
        if context.human_response is None:
            return Waiting(screen=ScreenType.ANSWER_FORM, data=QUESTION)
        if broken["on"]:
            raise RuntimeError("хранилище ответов недоступно")
        return Done()

    add_block("student.fake_broken", ask, kind="interactive", screen="answer_form")
    pipeline = graph([{"id": "ask", "type": "block", "block": "student.fake_broken"}])
    waiting = go.start(pipeline)

    failed = go.respond(pipeline, "ask", answer_with("8"))
    assert failed.status is RunStatus.ERROR
    assert failed.error.startswith("узел «ask»: блок «student.fake_broken» упал")
    assert failed.waiting == waiting.waiting
    # Блок, который ждёт человека, не повторяется: один вызов с ответом — и ошибка.
    assert called() == ["ask", "ask"]
    with pytest.raises(ResponseRejected):
        go.respond(pipeline, "ask", answer_with("8"))

    # Преподаватель продолжает запуск: экран тот же, блок без человека не вызывается.
    broken["on"] = False
    again = go.resume(pipeline)
    assert again.status is RunStatus.WAITING and again.error is None
    assert again.waiting == waiting.waiting
    assert called() == ["ask", "ask"]
    assert asyncio.run(go.store.load("run-1")) == again

    assert go.respond(pipeline, "ask", answer_with("8")).status is RunStatus.DONE


def test_pause_inside_a_loop(go, graph, ask, add_block, answer_with, called):
    """Как в сценарии 1: неверный ответ возвращает к тому же вопросу, верный — ведёт дальше."""

    async def check(inputs, config, context):
        correct = inputs["answer"]["text"] == "8"
        return Done(outcome="correct" if correct else "wrong")

    add_block(
        "check.fake_exact",
        check,
        inputs=[{"name": "answer", "title": "Ответ", "type": "Answer"}],
        outcomes=["correct", "wrong"],
    )
    pipeline = graph(
        [{**ASK, "inputs": {}, "limit": {"max": 3}}, CHECK],
        [("ask", "answer", "check"), ("check", "wrong", "ask")],
    )
    go.start(pipeline)

    state = go.respond(pipeline, "ask", answer_with("6"))
    assert state.status is RunStatus.WAITING and state.current == ["ask"]
    # Узел на паузе попытку не тратит: посчитан один пройденный раз, а не два вызова.
    assert state.counters == {"ask": 1}

    state = go.respond(pipeline, "ask", answer_with("8"))
    assert state.status is RunStatus.DONE
    assert called() == ["ask", "ask", "check", "ask", "ask", "check"]


def test_auto_block_cannot_wait_for_a_person(go, graph, add_block):
    async def ask(inputs, config, context):
        return Waiting(screen=ScreenType.ANSWER_FORM, data=QUESTION)

    add_block("transform.fake_asks", ask)
    pipeline = graph([{"id": "ask", "type": "block", "block": "transform.fake_asks"}])

    state = go.start(pipeline)

    assert state.status is RunStatus.ERROR and state.waiting == []
    assert "блок `kind: auto` не может ждать человека" in state.error
