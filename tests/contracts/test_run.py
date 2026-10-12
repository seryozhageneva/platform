"""Интерфейс run(): две формы результата и обмен «блок ждёт человека» в два шага."""

import asyncio

import pytest
from conftest import MANIFESTS
from pydantic import TypeAdapter, ValidationError

from backend.core.contracts.interfaces import LLMMessage, LLMResponse
from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import value_problems
from backend.core.contracts.run import (
    Done,
    RunContext,
    RunRequest,
    RunResult,
    Waiting,
    response_problems,
    result_problems,
)
from backend.core.contracts.screens import ScreenType

TASK = {
    "id": "t1",
    "subject": "math",
    "topic": "логарифмы",
    "difficulty": 2,
    "statement": "Вычисли $\\log_2 8$.",
    "check_method": "short_answer",
    "answer": "3",
}


def context(**fields) -> RunContext:
    return RunContext(run_id="r1", node_id="show", pipeline_id="p1", **fields)


async def show_task(inputs, config, context):
    """Учебный блок «показать задачу и принять ответ» — заглушка по контракту."""
    task = inputs["task"]
    if context.human_response is None:
        return Waiting(
            screen="answer_form",
            data={
                "task_id": task["id"],
                "statement": task["statement"],
                "forms": config["forms"],
            },
        )
    if context.human_response["action"] == "hint":
        return Done(outcome="hint_requested")
    return Done(outputs={"answer": context.human_response["answer"]}, outcome="answer")


def test_waiting_for_human_takes_two_calls():
    manifest = load_manifest(MANIFESTS / "student.show_task.yaml")
    inputs, config = {"task": TASK}, {"forms": ["text", "formula"]}

    # Шаг 1: блок не «висит», а сразу сообщает, какой экран показать.
    first = asyncio.run(show_task(inputs, config, context()))
    assert isinstance(first, Waiting) and first.screen is ScreenType.ANSWER_FORM
    assert result_problems(manifest, first) == []
    # Эталонный ответ в данные экрана не попал.
    assert "answer" not in first.data and "3" not in first.data.values()

    # Шаг 2: движок вызывает тот же run() ещё раз, положив ответ человека в context.
    response = {"action": "answer", "answer": {"task_id": "t1", "form": "text", "text": "3"}}
    assert response_problems(first.screen, response) == []
    again = context(shown=first.data, human_response=response)
    second = asyncio.run(show_task(inputs, config, again))
    assert isinstance(second, Done) and second.outcome == "answer"
    assert result_problems(manifest, second) == []
    assert value_problems(manifest.output("answer"), second.outputs["answer"]) == []


def test_student_can_only_answer_or_ask_for_hint():
    manifest = load_manifest(MANIFESTS / "student.show_task.yaml")
    asked = asyncio.run(
        show_task({"task": TASK}, {"forms": ["text"]}, context(human_response={"action": "hint"}))
    )
    assert asked.outcome == "hint_requested" and result_problems(manifest, asked) == []

    assert response_problems(ScreenType.ANSWER_FORM, {"action": "chat"}) != []
    assert response_problems(ScreenType.ANSWER_FORM, {"action": "answer"}) == [
        "документ: при действии «answer» нужен сам ответ"
    ]


def test_waiting_data_must_fit_the_screen():
    with pytest.raises(ValidationError):
        Waiting(screen="answer_form", data={"statement": "нет task_id и forms"})
    with pytest.raises(ValidationError):
        Waiting(screen="своя_страница", data={})


def test_result_must_match_manifest():
    show = load_manifest(MANIFESTS / "student.show_task.yaml")
    check = load_manifest(MANIFESTS / "check.code_tests.yaml")

    assert result_problems(show, Done(outcome="skipped")) == [
        "исход «skipped» не объявлен в манифесте; допустимо: answer, photo, hint_requested"
    ]
    assert result_problems(show, Done(outcome="answer", outputs={"grade": 5})) == [
        "выход «grade» не объявлен в манифесте"
    ]
    table = Waiting(
        screen="review_table", data={"columns": [{"key": "a", "title": "A"}], "rows": []}
    )
    assert result_problems(show, table) == [
        "блок просит экран «review_table», а в манифесте объявлен «answer_form»"
    ]
    assert result_problems(check, table) == ["блок `kind: auto` не может ждать человека"]


def test_result_is_parsed_from_json_by_status():
    """Так движок читает ответ блока-сервиса на POST /run."""
    parse = TypeAdapter(RunResult).validate_python
    assert isinstance(parse({"status": "done", "outcome": "correct"}), Done)
    waiting = parse(
        {
            "status": "waiting",
            "screen": "confirm_recognized",
            "data": {
                "file": {
                    "id": "f1",
                    "name": "решение.jpg",
                    "kind": "image",
                    "media_type": "image/jpeg",
                },
                "recognized": "x = 3",
            },
        }
    )
    assert isinstance(waiting, Waiting)
    with pytest.raises(ValidationError):
        parse({"status": "думаю"})


class FakeLLM:
    async def complete(self, messages, *, schema=None, model=None):
        return LLMResponse(text="Подумай, в какую степень нужно возвести 2.", model="fake")


def test_block_gets_the_model_through_context():
    """Блок не подключает слой ИИ-моделей: модель приходит в context как интерфейс."""

    async def tutor(inputs, config, context):
        reply = await context.llm.complete([LLMMessage(role="user", content="Дай подсказку")])
        return Done(outputs={"hint": {"task_id": "t1", "level": 1, "text": reply.text}})

    result = asyncio.run(tutor({}, {}, context(llm=FakeLLM())))
    assert result.outputs["hint"]["text"].startswith("Подумай")

    with pytest.raises(ValidationError):
        context(llm="не модель")


def test_block_does_not_repeat_expensive_work_after_the_pause():
    """При втором вызове блок получает данные экрана, который сам попросил показать."""
    photo = {"id": "f1", "name": "решение.jpg", "kind": "image", "media_type": "image/jpeg"}
    calls = []

    class Recognizer:
        async def complete(self, messages, *, schema=None, model=None):
            calls.append(messages)
            return LLMResponse(text="x = 3", model="fake")

    async def photo_to_latex(inputs, config, context):
        if context.human_response is None:
            reply = await context.llm.complete([LLMMessage(role="user", content="Распознай")])
            return Waiting(
                screen="confirm_recognized",
                data={"file": inputs["answer"]["file"], "recognized": reply.text},
            )
        if not context.human_response["confirmed"] and not context.human_response.get("corrected"):
            return Done(outcome="unreadable")
        text = context.human_response.get("corrected") or context.shown["recognized"]
        return Done(outputs={"answer": {"task_id": "t1", "form": "formula", "text": text}})

    inputs = {"answer": {"task_id": "t1", "form": "photo", "file": photo}}
    llm = Recognizer()
    first = asyncio.run(photo_to_latex(inputs, {}, context(llm=llm)))
    confirmed = context(llm=llm, shown=first.data, human_response={"confirmed": True})
    second = asyncio.run(photo_to_latex(inputs, {}, confirmed))

    # Ученик подтвердил ровно тот текст, который видел; модель второй раз не вызывалась.
    assert second.outputs["answer"]["text"] == "x = 3"
    assert len(calls) == 1


def test_services_are_not_sent_over_the_network():
    request = RunRequest(inputs={"task": TASK}, context=context(llm=FakeLLM(), student_id="s1"))
    body = request.model_dump(mode="json")
    assert "llm" not in body["context"] and "tools" not in body["context"]
    assert body["context"]["student_id"] == "s1"
