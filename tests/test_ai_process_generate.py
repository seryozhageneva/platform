import asyncio
from pathlib import Path

import pytest

from backend.core.contracts.interfaces import ToolInfo
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


# Агент с инструментами (задача 28, ADR 0035).

GRADES_TOOL = ToolInfo(
    server="moodle",
    name="get_course_grades",
    description="Журнал оценок курса",
    input_schema={"type": "object", "properties": {"course_id": {"type": "integer"}}},
    read_only=True,
)
JOURNAL = {"assignments": [{"assignment_id": 1, "name": "Лаба", "grades": []}], "outcome": "ok"}
AGENT_CONFIG = {
    "prompt": "Составь сводку по группе.",
    "result": {"type": "Data", "of": "digest"},
    "tools": ["moodle.get_course_grades"],
    "course_id": 2,
}
CALL = {"action": "call_tool", "tool": "moodle.get_course_grades", "arguments": {}}
DIGEST = {"summary": "Оценок пока нет."}


class FakeTools:
    """Подделка `ToolClient`: отвечает заранее заданным и запоминает вызовы."""

    def __init__(self, tools=(GRADES_TOOL,), answer=JOURNAL, error=None):
        self.tools = list(tools)
        self.answer = answer
        self.error = error
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        if self.error is not None:
            raise self.error
        return self.answer


def agent(llm, tools, config=AGENT_CONFIG, inputs=None):
    context = RunContext(run_id="run", node_id="digest", pipeline_id="weekly", llm=llm, tools=tools)
    return asyncio.run(run(inputs or {"data": {"students": 3}}, config, context))


def test_agent_asks_the_journal_and_then_finishes():
    llm = FakeLLM(
        [
            {**CALL, "arguments": {"course_id": 99, "note": "Сова: 2 из 5"}},
            {"action": "finish", "result": DIGEST},
        ]
    )
    tools = FakeTools()
    result = agent(llm, tools)
    assert result.outputs == {"result": DIGEST}
    # Курс задал преподаватель: агент не может заглянуть в чужой.
    assert tools.calls == [("moodle", "get_course_grades", {"course_id": 2})]
    assert [event.model_dump() for event in result.events] == [
        {
            "type": "tool_called",
            "data": {"tool": "moodle.get_course_grades", "arguments": {"course_id": 2}, "ok": True},
        }
    ]
    first, second = llm.calls
    assert first.messages[0].role == "system"
    assert "moodle.get_course_grades" in first.messages[0].content
    assert first.messages[1].content.startswith("Составь сводку по группе.")
    answer = second.messages[-1].content
    assert answer.startswith("Ответ инструмента moodle.get_course_grades:")
    assert '"name": "Лаба"' in answer
    assert "осталось: 4" in answer


def test_agent_can_finish_without_tools():
    llm = FakeLLM([{"action": "finish", "result": DIGEST}])
    tools = FakeTools()
    assert agent(llm, tools).outputs == {"result": DIGEST}
    assert tools.calls == []


def test_agent_cannot_call_a_tool_not_chosen_for_the_node():
    other = {**CALL, "tool": "moodle.get_submissions"}
    with pytest.raises(FakeLLMError, match="не подходит под схему"):
        agent(FakeLLM([other]), FakeTools())


def test_after_last_call_only_the_result_is_allowed():
    llm = FakeLLM([CALL, {"action": "finish", "result": DIGEST}])
    tools = FakeTools()
    result = agent(llm, tools, {**AGENT_CONFIG, "max_steps": 1})
    assert result.outputs == {"result": DIGEST}
    assert "oneOf" in llm.calls[0].schema
    assert llm.calls[1].schema["properties"]["action"] == {"const": "finish"}
    assert "кончились" in llm.calls[1].messages[-1].content
    with pytest.raises(FakeLLMError, match="не подходит под схему"):
        agent(FakeLLM([CALL, CALL]), FakeTools(), {**AGENT_CONFIG, "max_steps": 1})


def test_tool_error_goes_to_the_model_not_to_the_teacher():
    llm = FakeLLM([CALL, {"action": "finish", "result": DIGEST}])
    tools = FakeTools(error=RuntimeError("Moodle недоступен"))
    result = agent(llm, tools)
    assert result.outputs == {"result": DIGEST}
    assert result.events[0].data["ok"] is False
    assert "Moodle недоступен" in llm.calls[1].messages[-1].content


def test_long_tool_answer_is_cut():
    llm = FakeLLM([CALL, {"action": "finish", "result": DIGEST}])
    agent(llm, FakeTools(answer={"text": "а" * 50_000}))
    assert "(ответ обрезан)" in llm.calls[1].messages[-1].content
    assert len(llm.calls[1].messages[-1].content) < 21_000


@pytest.mark.parametrize(
    "tools",
    [
        FakeTools(tools=[]),
        FakeTools(tools=[GRADES_TOOL.model_copy(update={"read_only": False})]),
        None,
    ],
)
def test_agent_without_its_tools_fails_before_the_model(tools):
    llm = FakeLLM()
    with pytest.raises(RuntimeError, match="инструмент"):
        agent(llm, tools)
    assert llm.calls == []


def test_agent_result_keeps_schema_definitions():
    task_result = {**TASKS_CONFIG, "tools": ["moodle.get_course_grades"]}
    llm = FakeLLM([{"action": "finish", "result": [TASK]}])
    assert agent(llm, FakeTools(), task_result).outputs == {"result": [TASK]}
    assert "$defs" in llm.calls[0].schema


def test_config_accepts_only_tools_of_the_manifest():
    manifest = load_manifest(MANIFEST)
    assert [(ref.server, ref.tool) for ref in manifest.tools] == [("moodle", "get_course_grades")]
    assert config_problems(AGENT_CONFIG, manifest.config, {}) == []
    wrong = {**AGENT_CONFIG, "tools": ["moodle.save_grade"]}
    assert config_problems(wrong, manifest.config, {})
    assert config_problems({**AGENT_CONFIG, "max_steps": 11}, manifest.config, {})


def test_journal_needs_a_course():
    manifest = load_manifest(MANIFEST)
    without_course = {key: value for key, value in AGENT_CONFIG.items() if key != "course_id"}
    assert config_problems(without_course, manifest.config, {})
