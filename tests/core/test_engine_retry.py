"""Повтор упавшего блока: автоматический блок вызывается снова, до трёх раз подряд.

Так запуск переживает короткий сбой — например, модель или Moodle ответили не сразу. Если не
помог и третий повтор, запуск получает статус «ошибка» и ждёт, пока его продолжат (ADR 0008).
"""

import pytest

from backend.core.contracts.run import Done, Waiting
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunStatus
from backend.core.engine import MAX_RETRIES

UPPER = {
    "id": "upper",
    "type": "block",
    "block": "transform.fake_flaky",
    "inputs": {"text": "make.text"},
}
TEXT = {"name": "text", "title": "Текст", "type": "Text"}


@pytest.fixture
def flaky(graph, add_block):
    """Пайплайн с блоком, который падает заданное число раз, а потом работает."""
    left = {"failures": 0}

    async def upper(inputs, config, context):
        if left["failures"] > 0:
            left["failures"] -= 1
            raise RuntimeError("модель недоступна")
        return Done(outputs={"text": {"text": inputs["text"]["text"].upper()}})

    add_block("transform.fake_flaky", upper, inputs=[TEXT], outputs=[TEXT])
    make = {
        "id": "make",
        "type": "block",
        "block": "source.fake_text",
        "config": {"text": "привет"},
    }
    return left, graph([make, UPPER], [("make", None, "upper")])


def attempts(calls) -> list[int]:
    return [context.attempt for node, _, _, context in calls if node == "upper"]


def test_block_that_fails_twice_is_called_again_and_the_run_goes_on(go, flaky, calls):
    left, pipeline = flaky
    left["failures"] = 2

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE and state.error is None
    assert state.ports["upper"]["text"] == {"text": "ПРИВЕТ"}
    # Блок видит номер попытки.
    assert attempts(calls) == [1, 2, 3]
    reason = "блок «transform.fake_flaky» упал: RuntimeError: модель недоступна"
    assert go.journal("attempt_failed", "node_failed") == [
        ("upper", "attempt_failed", {"attempt": 1, "error": reason}),
        ("upper", "attempt_failed", {"attempt": 2, "error": reason}),
    ]


def test_block_that_keeps_failing_stops_the_run_after_three_retries(go, flaky, calls):
    left, pipeline = flaky
    left["failures"] = 100

    state = go.start(pipeline)

    assert MAX_RETRIES == 3
    assert state.status is RunStatus.ERROR
    assert state.error == (
        "узел «upper»: блок «transform.fake_flaky» упал: RuntimeError: модель недоступна"
    )
    # Первый вызов и три повтора.
    assert attempts(calls) == [1, 2, 3, 4]
    assert [kind for _, kind, _ in go.journal("attempt_failed", "node_failed")] == [
        "attempt_failed",
        "attempt_failed",
        "attempt_failed",
        "node_failed",
    ]
    assert state.current == ["upper"] and "upper" not in state.ports


def test_attempts_are_counted_anew_when_the_run_is_continued(go, flaky, calls):
    left, pipeline = flaky
    left["failures"] = 5
    assert go.start(pipeline).status is RunStatus.ERROR

    state = go.resume(pipeline)

    # Четыре вызова до остановки; после продолжения — ещё один сбой и удачная вторая попытка.
    assert state.status is RunStatus.DONE
    assert attempts(calls) == [1, 2, 3, 4, 1, 2]


def test_every_attempt_gets_the_inputs_untouched(go, graph, add_block, calls):
    seen = []

    async def upper_in_place(inputs, config, context):
        seen.append(inputs["text"]["text"])
        inputs["text"]["text"] = inputs["text"]["text"].upper()
        if context.attempt == 1:
            raise RuntimeError("сбой после правки входа")
        return Done(outputs={"text": inputs["text"]})

    add_block("transform.fake_flaky", upper_in_place, inputs=[TEXT], outputs=[TEXT])
    make = {
        "id": "make",
        "type": "block",
        "block": "source.fake_text",
        "config": {"text": "привет"},
    }

    state = go.start(graph([make, UPPER], [("make", None, "upper")]))

    assert state.status is RunStatus.DONE
    assert seen == ["привет", "привет"]


def test_block_that_waits_for_a_person_is_not_called_again(go, graph, add_block, called):
    async def ask(inputs, config, context):
        raise RuntimeError("не удалось показать задачу")

    add_block("student.fake_broken", ask, kind="interactive", screen="answer_form")
    pipeline = graph([{"id": "ask", "type": "block", "block": "student.fake_broken"}])

    state = go.start(pipeline)

    assert state.status is RunStatus.ERROR
    assert called() == ["ask"]
    assert go.journal("attempt_failed") == []


def test_result_that_breaks_the_manifest_is_not_a_reason_to_retry(go, graph, add_block, called):
    async def wrong(inputs, config, context):
        return Done(outcome="maybe")

    add_block("transform.fake_wrong", wrong)
    pipeline = graph([{"id": "wrong", "type": "block", "block": "transform.fake_wrong"}])

    state = go.start(pipeline)

    # Это ошибка в самом блоке: повтор вернул бы то же самое.
    assert state.status is RunStatus.ERROR and "исход «maybe» не объявлен" in state.error
    assert called() == ["wrong"]


def test_auto_block_that_waits_is_not_retried_either(go, graph, add_block, called):
    async def ask(inputs, config, context):
        data = {"task_id": "t1", "statement": "Вычислите $2^3$.", "forms": ["text"]}
        return Waiting(screen=ScreenType.ANSWER_FORM, data=data)

    add_block("transform.fake_asks", ask)
    pipeline = graph([{"id": "ask", "type": "block", "block": "transform.fake_asks"}])

    assert go.start(pipeline).status is RunStatus.ERROR
    assert called() == ["ask"]
