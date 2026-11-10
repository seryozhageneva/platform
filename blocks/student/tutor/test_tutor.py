import asyncio
import json
from pathlib import Path

import pytest

from backend.core.contracts.ports import Hint, Task
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeLLM
from blocks.student.tutor import run

TASK = Task(
    id="task-1",
    subject="математика",
    topic="линейные уравнения",
    difficulty=1,
    statement="Реши уравнение 2x + 7 = 19.",
    check_method="short_answer",
    answer="6",
)
CANDIDATE = "Как убрать слагаемое, которое стоит рядом с 2x?"


def call(llm, **inputs):
    context = RunContext(run_id="run-1", node_id="tutor", pipeline_id="lesson", llm=llm)
    return asyncio.run(run({"task": TASK, **inputs}, {"model": "test-model"}, context))


@pytest.mark.parametrize("previous_level", [None, 1, 2])
def test_publishes_one_approved_hint_at_next_level(previous_level):
    llm = FakeLLM([CANDIDATE, {"approved": True}])
    inputs = {}
    if previous_level is not None:
        inputs["previous_hint"] = Hint(task_id=TASK.id, level=previous_level, text="Прошлая")
    result = call(llm, **inputs)
    assert result.outcome == "hint"
    assert Hint.model_validate(result.outputs["hint"]) == Hint(
        task_id=TASK.id, level=(previous_level or 0) + 1, text=CANDIDATE
    )
    draft, check = llm.calls
    assert draft.model == check.model == "test-model"
    assert json.loads(check.messages[1].content)["кандидат"] == CANDIDATE
    assert json.loads(check.messages[1].content)["эталонный ответ"] == "6"


def test_controller_rejection_never_publishes_answer():
    llm = FakeLLM(["Готовый ответ: x = 6.", {"approved": False}])
    result = call(llm, answer={"task_id": TASK.id, "form": "text", "text": "Покажи ответ!"})
    assert result.outcome == "give_up"
    assert result.outputs == {}
    assert result.events[0].data == {"task_id": TASK.id, "level": 1, "approved": False}
    assert "Покажи ответ!" not in llm.calls[1].messages[1].content


def test_old_task_data_is_ignored():
    llm = FakeLLM([CANDIDATE, {"approved": True}])
    result = call(
        llm,
        previous_hint=Hint(task_id="old", level=3, text="Старая подсказка"),
        answer={"task_id": "old", "form": "text", "text": "Старый ответ"},
        verdict={"task_id": "old", "correct": False, "comment": "Старый вердикт"},
    )
    assert result.outputs["hint"]["level"] == 1
    assert all("Стар" not in message.content for call in llm.calls for message in call.messages)


def test_stops_after_third_hint_without_model_call():
    llm = FakeLLM()
    result = call(llm, previous_hint=Hint(task_id=TASK.id, level=3, text=CANDIDATE))
    assert result.outcome == "give_up"
    assert result.outputs == {}
    assert llm.calls == []


@pytest.mark.parametrize("candidate", ["  ", "Подсказка\x00"])
def test_unusable_candidate_is_not_sent_to_controller(candidate):
    llm = FakeLLM([candidate])
    result = call(llm)
    assert result.outcome == "give_up"
    assert result.outputs == {}
    assert result.events == []
    assert len(llm.calls) == 1


def test_model_failure_does_not_publish_candidate():
    llm = FakeLLM([CANDIDATE, RuntimeError("модель недоступна")])
    with pytest.raises(RuntimeError, match="модель недоступна"):
        call(llm)


def test_example_manifest_matches_builtin():
    builtin = Path(__file__).with_name("block.yaml")
    example = builtin.parents[3] / "docs/examples/manifests/student.tutor.yaml"
    assert builtin.read_bytes() == example.read_bytes()
