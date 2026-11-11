import asyncio
import json

import pytest

from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeLLM
from blocks.check.rubric import run

TASK = {
    "id": "fraction",
    "subject": "Математика",
    "topic": "Дроби",
    "difficulty": 1,
    "statement": "Объясни, почему 1/2 = 2/4.",
    "check_method": "long_answer",
    "rubric": "2 балла за объяснение умножения числителя и знаменателя.",
    "solution": "Служебный эталон.",
}
ANSWER = {"task_id": TASK["id"], "form": "text", "text": "Умножим обе части дроби на 2."}


def context(llm):
    return RunContext(run_id="run", node_id="grade", pipeline_id="lesson", llm=llm)


@pytest.mark.parametrize(("score", "outcome"), [(2, "correct"), (1, "wrong"), (0, "wrong")])
def test_answer_with_task_gets_preliminary_verdict(score, outcome):
    llm = FakeLLM([{"score": score, "max_score": 2, "comment": "Проверка по критерию."}])
    result = asyncio.run(
        run({"task": TASK, "work": ANSWER}, {"rubric": "Другая рубрика"}, context(llm))
    )
    assert result.outcome == outcome
    assert result.outputs["verdict"] == {
        "correct": outcome == "correct",
        "task_id": TASK["id"],
        "score": score,
        "max_score": 2,
        "comment": "Проверка по критерию.",
        "preliminary": True,
    }
    system, work = llm.calls[0].messages
    assert system.role == "system"
    assert system.content.endswith(
        json.dumps({"rubric": TASK["rubric"], "statement": TASK["statement"]}, ensure_ascii=False)
    )
    assert work.role == "user"
    assert json.loads(work.content) == {"work": ANSWER["text"]}


def test_document_uses_configured_rubric():
    llm = FakeLLM([{"score": 0.5, "max_score": 1, "comment": "Есть начало."}])
    result = asyncio.run(
        run(
            {"work": {"text": "Начало доклада"}},
            {"rubric": "Полнота", "model": "model"},
            context(llm),
        )
    )
    assert result.outputs["verdict"]["task_id"] is None
    assert llm.calls[0].messages[0].content.endswith('{"rubric": "Полнота"}')
    assert llm.calls[0].model == "model"


@pytest.mark.parametrize(
    "reply",
    [
        {"score": 3, "max_score": 2, "comment": "Слишком много."},
        {"score": 0, "max_score": 2, "comment": "  "},
    ],
)
def test_invalid_grade_stops_block(reply):
    with pytest.raises(ValueError, match="недопустимую оценку"):
        asyncio.run(run({"task": TASK, "work": ANSWER}, {}, context(FakeLLM([reply]))))


def test_missing_rubric_and_mismatched_answer_never_call_model():
    llm = FakeLLM([])
    with pytest.raises(ValueError, match="нужна рубрика"):
        asyncio.run(run({"work": "Текст"}, {}, context(llm)))
    with pytest.raises(ValueError, match="к другой задаче"):
        asyncio.run(run({"task": TASK, "work": {**ANSWER, "task_id": "other"}}, {}, context(llm)))
    assert llm.calls == []
