import asyncio
from pathlib import Path

import pytest

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeLLM, FakeLLMError
from backend.core.validator import config_problems
from blocks.ai_process.generate import run

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "blocks/ai_process/generate/block.yaml"
SUMMARY_CONFIG = {
    "prompt": "Лекция: {data}\nОпорные сведения: {context}",
    "result": {"type": "Data", "of": "summary"},
    "result_schema": "lecture_summary",
}
TASKS_CONFIG = {
    "prompt": "Составь задания.",
    "result": {"type": "Task", "list": True},
    "result_schema": "lecture_tasks",
}
TASK = {
    "id": "fractions-1",
    "subject": "математика",
    "topic": "дроби",
    "difficulty": 1,
    "statement": "Сложи 1/4 и 2/4.",
    "check_method": "short_answer",
    "answer": "3/4",
    "solution": "Сложи числители, сохрани знаменатель.",
}


def generate(llm, inputs, config):
    context = RunContext(run_id="run", node_id="generate", pipeline_id="materials", llm=llm)
    return asyncio.run(run(inputs, config, context))


def test_summary_substitutes_inputs_once():
    summary = {"summary": "Складываем числители.", "key_concepts": ["знаменатель"]}
    llm = FakeLLM([summary])
    result = generate(
        llm,
        {"data": "Лекция о дробях. Пример записи: {context}.", "context": {"class": 5}},
        {**SUMMARY_CONFIG, "model": "test-model"},
    )
    assert result.outputs == {"result": summary}
    (call,) = llm.calls
    assert call.messages[0].content == (
        'Лекция: Лекция о дробях. Пример записи: {context}.\nОпорные сведения: {"class": 5}'
    )
    assert call.model == "test-model"


def test_tasks_with_legacy_prompt_append_inputs():
    llm = FakeLLM([[TASK]])
    result = generate(llm, {"data": "Текст лекции", "context": "Конспект"}, TASKS_CONFIG)
    assert result.outputs == {"result": [TASK]}
    (call,) = llm.calls
    assert call.messages[0].content == (
        "Составь задания.\n\nИсходные данные:\nТекст лекции\n\nДополнительные данные:\nКонспект"
    )


def test_optional_context_can_be_absent():
    llm = FakeLLM([{"summary": "Конспект", "key_concepts": ["дробь"]}])
    generate(llm, {"data": "Дроби"}, SUMMARY_CONFIG)
    assert llm.calls[0].messages[0].content == "Лекция: Дроби\nОпорные сведения: не передано"


@pytest.mark.parametrize("reply", [[], [{**TASK, "answer": None}], [{**TASK, "solution": ""}]])
def test_lecture_tasks_reject_missing_answer_or_solution(reply):
    with pytest.raises(FakeLLMError, match="не подходит под схему"):
        generate(FakeLLM([reply]), {"data": "Лекция"}, TASKS_CONFIG)


def test_summary_rejects_missing_concepts():
    with pytest.raises(FakeLLMError, match="не подходит под схему"):
        generate(FakeLLM([{"summary": "Лекция о дробях"}]), {"data": "Лекция"}, SUMMARY_CONFIG)


@pytest.mark.parametrize("preset", ["unknown", "lecture_tasks", {"type": "object"}])
def test_rejects_invalid_schema_selection_before_model_call(preset):
    llm = FakeLLM()
    with pytest.raises(ValueError, match="схема результата"):
        generate(llm, {"data": "Лекция"}, {**SUMMARY_CONFIG, "result_schema": preset})
    assert not llm.calls


def test_answer_without_preset_uses_port_contract():
    config = {"prompt": "Реши задачу.", "result": {"type": "Answer"}}
    answer = {"task_id": "test", "form": "formula", "text": "3/4"}
    assert generate(FakeLLM([answer]), {"data": TASK}, config).outputs == {"result": answer}
    with pytest.raises(ValueError, match="у ответа должен быть текст"):
        generate(FakeLLM([{**answer, "text": None}]), {"data": TASK}, config)


def test_manifest_matches_its_example():
    assert load_manifest(MANIFEST) == load_manifest(
        ROOT / "docs/examples/manifests/ai_process.generate.yaml"
    )


@pytest.mark.parametrize(
    ("config", "wrong_result", "error"),
    [
        (SUMMARY_CONFIG, {"type": "Data", "of": "digest"}, "result.of"),
        (SUMMARY_CONFIG, {"type": "Data"}, "«of»"),
        (SUMMARY_CONFIG, {"type": "Data", "of": "summary", "list": True}, "result.list"),
        (TASKS_CONFIG, {"type": "Answer", "list": True}, "result.type"),
        (TASKS_CONFIG, {"type": "Task"}, "«list»"),
        (TASKS_CONFIG, {"type": "Task", "list": False}, "result.list"),
    ],
)
def test_config_validation_rejects_incompatible_preset(config, wrong_result, error):
    schema = load_manifest(MANIFEST).config
    assert config_problems(config, schema, {}) == []
    problems = config_problems({**config, "result": wrong_result}, schema, {})
    assert len(problems) == 1
    assert error in problems[0]


def test_data_fields_hide_everything_else_from_the_model():
    config = {
        "prompt": "Реши задачу: {data}",
        "result": {"type": "Answer"},
        "data_fields": ["id", "statement"],
    }
    assert config_problems(config, load_manifest(MANIFEST).config, {}) == []
    llm = FakeLLM([{"task_id": TASK["id"], "form": "text", "text": "3/4"}])
    generate(llm, {"data": TASK}, config)
    [call] = llm.calls
    [message] = call.messages
    assert TASK["statement"] in message.content
    assert TASK["answer"] not in message.content
    assert TASK["solution"] not in message.content

    many = FakeLLM([{"task_id": TASK["id"], "form": "text", "text": "3/4"}])
    generate(many, {"data": [TASK, {**TASK, "id": "fractions-2"}]}, config)
    assert "fractions-2" in many.calls[0].messages[0].content
    assert TASK["solution"] not in many.calls[0].messages[0].content


def test_data_fields_need_a_record():
    config = {"prompt": "{data}", "result": {"type": "Text"}, "data_fields": ["statement"]}
    with pytest.raises(ValueError, match="только у записи"):
        generate(FakeLLM([{"text": "x"}]), {"data": "Просто текст"}, config)
