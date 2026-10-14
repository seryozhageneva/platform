"""Блок «Источник: банк задач» на подделке хранилища: без базы и без модели.

Задачи выдуманные. Хранилище-подделка `FakeStore` ищет так же, как настоящее: по совпадению
условий, в том порядке, в каком задачи переданы.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import CheckMethod, Task
from backend.core.contracts.run import Done, RunContext
from backend.core.contracts.testing import FakeStore
from blocks.source.task_bank import run

HERE = Path(__file__).parent
EXAMPLE = HERE.parents[2] / "docs" / "examples" / "manifests" / "source.task_bank.yaml"


def task(task_id: str, difficulty: int = 1, topic: str = "logarithms", **fields: Any) -> Task:
    return Task(
        id=task_id,
        subject=fields.pop("subject", "math"),
        topic=topic,
        difficulty=difficulty,
        statement=f"Задача {task_id}",
        check_method=CheckMethod.SHORT_ANSWER,
        answer="1",
        **fields,
    )


def take(
    tasks: list[Task],
    config: dict[str, Any] | None = None,
    *,
    previous: Task | None = None,
    correct: bool | None = None,
    verdict_task_id: str | None = None,
    run_id: str = "run-1",
    store: FakeStore | None = None,
) -> Done:
    inputs: dict[str, Any] = {}
    if previous is not None:
        inputs["previous"] = previous.model_dump(mode="json")
    if correct is not None:
        about = verdict_task_id or (previous.id if previous else None)
        inputs["verdict"] = {"correct": correct, "task_id": about}
    context = RunContext(
        run_id=run_id,
        node_id="take_task",
        pipeline_id="scenario_1_training",
        store=store if store is not None else FakeStore(tasks),
    )
    config = {"topic": "logarithms", "difficulty": 1, "adapt": True, **(config or {})}
    return asyncio.run(run(inputs, config, context))


def chosen(result: Done) -> str:
    assert result.outcome == "ok"
    return result.outputs["task"]["id"]


def test_task_is_taken_by_topic_and_start_difficulty():
    tasks = [task("easy", 1), task("hard", 2), task("other", 2, topic="derivatives")]

    result = take(tasks, {"difficulty": 2})

    assert chosen(result) == "hard"
    assert result.outputs["task"]["topic"] == "logarithms"
    assert [(event.type, event.data) for event in result.events] == [
        ("task_chosen", {"task_id": "hard", "difficulty": 2, "reason": "start"})
    ]


def test_subject_narrows_the_search():
    tasks = [task("math", 1), task("informatics", 1, subject="informatics")]

    assert chosen(take(tasks, {"subject": "informatics"})) == "informatics"


def test_task_is_taken_by_its_number():
    tasks = [task("first", 1), task("second", 3)]

    result = take(tasks, {"task_id": "second"})

    assert chosen(result) == "second"
    assert result.events[0].data["reason"] == "task_id"


def test_unknown_task_number_gives_empty():
    result = take([task("first")], {"task_id": "missing"})

    assert result.outcome == "empty"
    assert result.outputs == {}
    assert [(event.type, event.data) for event in result.events] == [
        ("no_tasks", {"task_id": "missing"})
    ]


def test_no_tasks_of_the_topic_gives_empty_and_says_why():
    result = take([task("other", 1, topic="derivatives")], {"difficulty": 1})

    assert result.outcome == "empty"
    assert [(event.type, event.data) for event in result.events] == [
        ("no_tasks", {"topic": "logarithms", "subject": None, "difficulty": 1})
    ]


def test_start_difficulty_is_strict():
    """На стартовой сложности задач нет — блок не подбирает другую сам."""
    result = take([task("hard", 2)], {"difficulty": 1})

    assert result.outcome == "empty"


def test_difficulty_goes_up_after_a_correct_answer():
    previous = task("p", 2)
    tasks = [previous, task("same", 2), task("harder", 3)]

    result = take(tasks, previous=previous, correct=True)

    assert chosen(result) == "harder"
    assert result.events[0].data["reason"] == "harder"


def test_difficulty_goes_down_after_a_wrong_answer():
    previous = task("p", 2)
    tasks = [task("easier", 1), previous, task("harder", 3)]

    result = take(tasks, previous=previous, correct=False)

    assert chosen(result) == "easier"
    assert result.events[0].data["reason"] == "easier"


def test_difficulty_does_not_go_below_one():
    previous = task("p", 1)
    tasks = [previous, task("same", 1)]

    result = take(tasks, previous=previous, correct=False)

    assert chosen(result) == "same"
    assert result.events[0].data["reason"] == "same"


def test_difficulty_stays_when_there_are_no_tasks_at_the_next_level():
    previous = task("p", 3)
    tasks = [previous, task("same", 3)]

    assert chosen(take(tasks, previous=previous, correct=True)) == "same"


def test_no_tasks_at_the_next_and_the_previous_level_gives_empty():
    previous = task("p", 3)

    result = take([task("other", 1)], previous=previous, correct=True)

    assert result.outcome == "empty"
    assert result.events[0].data["difficulty"] == 4


def test_previous_task_is_not_repeated_when_there_are_others():
    previous = task("p", 1)
    tasks = [previous, task("other", 1)]

    for run_id in ("run-1", "run-2", "run-3", "run-4"):
        assert chosen(take(tasks, previous=previous, correct=False, run_id=run_id)) == "other"


def test_previous_task_is_repeated_when_it_is_the_only_one():
    previous = task("p", 1)

    assert chosen(take([previous], previous=previous, correct=False)) == "p"


def test_verdict_about_another_task_does_not_change_difficulty():
    previous = task("p", 2)
    tasks = [task("start", 1), previous, task("harder", 3)]

    result = take(tasks, previous=previous, correct=True, verdict_task_id="someone_else")

    assert chosen(result) == "start"


def test_without_adapt_difficulty_is_always_the_start_one():
    previous = task("p", 2)
    tasks = [task("start", 1), previous, task("harder", 3)]

    result = take(tasks, {"adapt": False}, previous=previous, correct=True)

    assert chosen(result) == "start"


def test_choice_is_repeatable_within_a_run():
    """Повтор упавшего блока в том же запуске даёт ту же задачу."""
    tasks = [task(f"t{number}", 1) for number in range(10)]

    first = {chosen(take(tasks, run_id="run-7")) for _ in range(5)}
    across_runs = {chosen(take(tasks, run_id=f"run-{number}")) for number in range(30)}

    assert len(first) == 1
    # Разные запуски получают разные задачи: выбор всё-таки случайный.
    assert len(across_runs) > 1


def test_config_defaults_are_used_when_not_given():
    context = RunContext(
        run_id="run-1", node_id="take_task", pipeline_id="p", store=FakeStore([task("one", 1)])
    )

    result = asyncio.run(run({}, {"topic": "logarithms"}, context))

    assert chosen(result) == "one"


def test_block_without_a_store_fails_clearly():
    context = RunContext(run_id="run-1", node_id="take_task", pipeline_id="p")

    with pytest.raises(RuntimeError, match="хранилище платформы"):
        asyncio.run(run({}, {"topic": "logarithms"}, context))


def test_example_manifest_is_a_copy_of_the_block_manifest():
    assert load_manifest(EXAMPLE) == load_manifest(HERE / "block.yaml")
