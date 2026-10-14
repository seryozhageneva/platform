"""Блок «Показать задачу и принять ответ»: без базы, без модели и без хранилища.

Блоку нужны только вход «задача», настройки и — при втором вызове — данные показанного
экрана и ответ ученика. Задачи и ответы выдуманные.
"""

import asyncio
from pathlib import Path
from typing import Any

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import CheckMethod, Hint, Task
from backend.core.contracts.run import Done, RunContext, Waiting, result_problems
from backend.core.contracts.screens import ScreenType
from blocks.student.show_task import run

HERE = Path(__file__).parent
EXAMPLE = HERE.parents[2] / "docs" / "examples" / "manifests" / "student.show_task.yaml"
MANIFEST = load_manifest(HERE / "block.yaml")

TASK = Task(
    id="task-1",
    subject="math",
    topic="logarithms",
    difficulty=1,
    statement="Найдите $\\log_2 8$.",
    check_method=CheckMethod.SHORT_ANSWER,
    answer="3",
    solution="$2^3 = 8$, значит ответ 3.",
)


def context(shown: dict[str, Any] | None = None, response: dict[str, Any] | None = None):
    return RunContext(
        run_id="run-1",
        node_id="show",
        pipeline_id="scenario_1_training",
        shown=shown,
        human_response=response,
    )


def show(config: dict[str, Any] | None = None, hint: Hint | None = None) -> Waiting:
    inputs: dict[str, Any] = {"task": TASK.model_dump(mode="json")}
    if hint is not None:
        inputs["hint"] = hint.model_dump(mode="json")
    result = asyncio.run(run(inputs, config or {}, context()))
    assert isinstance(result, Waiting)
    assert result_problems(MANIFEST, result) == []
    return result


def reply(response: dict[str, Any], config: dict[str, Any] | None = None) -> Done | Waiting:
    """Второй вызов: экран показан, ученик ответил."""
    shown = show(config).data
    inputs = {"task": TASK.model_dump(mode="json")}
    result = asyncio.run(run(inputs, config or {}, context(shown, response)))
    assert result_problems(MANIFEST, result) == []
    return result


def answer(text: str | None = "3", form: str = "text", task_id: str = "task-1", **extra: Any):
    return {"action": "answer", "answer": {"task_id": task_id, "form": form, "text": text, **extra}}


def test_first_call_shows_the_answer_form_with_the_statement():
    result = show()

    assert result.screen is ScreenType.ANSWER_FORM
    assert result.data["task_id"] == "task-1"
    assert result.data["statement"] == TASK.statement
    assert [(event.type, event.data) for event in result.events] == [
        ("task_shown", {"task_id": "task-1", "hint_level": None})
    ]


def test_screen_has_neither_the_answer_nor_the_solution():
    data = show().data

    assert "answer" not in data and "solution" not in data
    assert "$2^3 = 8$" not in str(data)


def test_defaults_are_used_when_config_is_empty():
    data = show().data

    assert data["forms"] == ["text", "formula"]
    assert data["can_ask_hint"] is True


def test_forms_and_hints_come_from_config():
    data = show({"forms": ["code"], "allow_hints": False}).data

    assert data["forms"] == ["code"]
    assert data["can_ask_hint"] is False


def test_hint_for_this_task_is_shown():
    result = show(hint=Hint(task_id="task-1", level=2, text="Вспомните, что $2^3 = 8$."))

    assert result.data["hint"]["level"] == 2
    assert result.events[0].data["hint_level"] == 2


def test_hint_for_the_previous_task_is_not_shown():
    data = show(hint=Hint(task_id="old-task", level=1, text="Подсказка к прошлой задаче")).data

    assert data["hint"] is None


def test_text_answer_gives_outcome_answer():
    result = reply(answer("3"))

    assert isinstance(result, Done)
    assert result.outcome == "answer"
    assert result.outputs["answer"]["text"] == "3"
    assert result.outputs["answer"]["task_id"] == "task-1"


def test_photo_answer_gives_outcome_photo():
    photo = {"id": "file-1", "name": "solution.jpg", "kind": "image", "media_type": "image/jpeg"}
    config = {"forms": ["text", "photo"]}

    result = reply(answer(None, form="photo", file=photo), config)

    assert isinstance(result, Done)
    assert result.outcome == "photo"
    assert result.outputs["answer"]["file"]["id"] == "file-1"


def test_asking_for_a_hint_gives_hint_requested_without_outputs():
    result = reply({"action": "hint"})

    assert isinstance(result, Done)
    assert result.outcome == "hint_requested"
    assert result.outputs == {}
    assert [(event.type, event.data) for event in result.events] == [
        ("hint_requested", {"task_id": "task-1"})
    ]


def refusal(result: Done | Waiting) -> str:
    """Причина переспроса; заодно проверяет, что экран остался тем же."""
    assert isinstance(result, Waiting)
    assert result.screen is ScreenType.ANSWER_FORM
    assert result.data["task_id"] == "task-1"
    [event] = result.events
    assert event.type == "response_refused"
    return event.data["reason"]


def test_hint_is_refused_when_hints_are_off():
    assert refusal(reply({"action": "hint"}, {"allow_hints": False})) == "hints_off"


def test_answer_to_another_task_is_refused():
    assert refusal(reply(answer(task_id="old-task"))) == "other_task"


def test_answer_in_a_form_that_is_not_allowed_is_refused():
    assert refusal(reply(answer("print(3)", form="code"))) == "form_not_allowed"


def test_empty_answer_is_refused():
    assert refusal(reply(answer("   "))) == "empty_answer"


def test_answer_with_a_null_character_is_refused():
    """Нулевой символ база не записывает: блок переспрашивает, а не ломает запуск."""
    assert refusal(reply(answer("3\x00"))) == "bad_characters"


def test_answer_text_does_not_get_into_the_journal():
    secret = "ответ-который-нельзя-в-журнал"

    accepted = reply(answer(secret))
    refused = reply(answer(secret, task_id="old-task"))

    for result in (accepted, refused):
        assert secret not in str([event.data for event in result.events])
    assert [(event.type, event.data) for event in accepted.events] == [
        ("answer_received", {"task_id": "task-1", "form": "text"})
    ]


def test_example_manifest_is_a_copy_of_the_block_manifest():
    assert load_manifest(EXAMPLE) == MANIFEST
