"""Подделки служб: фейковая модель отвечает заданным в тесте, подделка хранилища ищет задачи."""

import asyncio

import pytest

from backend.core.contracts.interfaces import LLMClient, LLMMessage, PlatformStore
from backend.core.contracts.ports import CheckMethod, Task
from backend.core.contracts.run import Done, RunContext
from backend.core.contracts.testing import FakeLLM, FakeLLMError, FakeStore

ASK = [LLMMessage(role="user", content="Дай подсказку к задаче")]
HINT_SCHEMA = {
    "type": "object",
    "properties": {"level": {"type": "integer"}, "text": {"type": "string"}},
    "required": ["level", "text"],
}


def complete(llm: FakeLLM, **options):
    return asyncio.run(llm.complete(ASK, **options))


def test_fake_model_fits_the_contract_interface():
    assert isinstance(FakeLLM(), LLMClient)


def test_replies_come_in_the_order_they_were_given():
    llm = FakeLLM(["первая подсказка", "вторая подсказка"])

    assert complete(llm).text == "первая подсказка"
    assert complete(llm).text == "вторая подсказка"


def test_plain_reply_carries_no_data():
    reply = complete(FakeLLM(["Подумай о степенях двойки."]))

    assert reply.data is None
    assert reply.model == "fake"
    assert (reply.input_tokens, reply.output_tokens) == (4, 4)


def test_reply_by_schema_comes_as_data():
    hint = {"level": 1, "text": "Чему равно 2 в кубе?"}

    reply = complete(FakeLLM([hint]), schema=HINT_SCHEMA)

    assert reply.data == hint
    assert '"level": 1' in reply.text


def test_text_reply_in_json_is_parsed_when_schema_is_given():
    reply = complete(FakeLLM(['{"level": 2, "text": "Вспомни определение."}']), schema=HINT_SCHEMA)

    assert reply.data == {"level": 2, "text": "Вспомни определение."}


def test_calls_are_remembered():
    llm = FakeLLM(["ответ"])

    complete(llm, schema=None, model="GigaChat-2-Max")

    (call,) = llm.calls
    assert call.messages == ASK
    assert call.schema is None
    assert call.model == "GigaChat-2-Max"


def test_requested_model_name_is_returned():
    assert complete(FakeLLM(["ответ"]), model="GigaChat-2-Max").model == "GigaChat-2-Max"


def test_running_out_of_replies_is_a_clear_error():
    llm = FakeLLM(["единственный ответ"])
    complete(llm)

    with pytest.raises(FakeLLMError, match="не хватило ответов: это вызов № 2"):
        complete(llm)


def test_default_reply_is_used_when_replies_run_out():
    llm = FakeLLM(["первый"], default="запасной")

    assert [complete(llm).text for _ in range(3)] == ["первый", "запасной", "запасной"]


def test_reply_that_does_not_fit_the_schema_is_a_clear_error():
    with pytest.raises(FakeLLMError, match="не подходит под схему"):
        complete(FakeLLM([{"level": "первый"}]), schema=HINT_SCHEMA)


def test_text_that_is_not_json_does_not_pass_for_a_reply_by_schema():
    with pytest.raises(FakeLLMError, match="не в формате JSON"):
        complete(FakeLLM(["просто текст"]), schema=HINT_SCHEMA)


def test_model_can_fail_on_demand():
    llm = FakeLLM([RuntimeError("модель недоступна"), "ответ со второй попытки"])

    with pytest.raises(RuntimeError, match="модель недоступна"):
        complete(llm)
    assert complete(llm).text == "ответ со второй попытки"


def test_block_gets_the_fake_model_through_context():
    """Так фейковой моделью пользуется тест блока: кладёт её в `context.llm`."""

    async def tutor(inputs, config, context: RunContext) -> Done:
        reply = await context.llm.complete(ASK, schema=HINT_SCHEMA)
        return Done(outputs={"hint": reply.data})

    llm = FakeLLM([{"level": 1, "text": "Чему равно 2 в кубе?"}])
    context = RunContext(run_id="run-1", node_id="tutor", pipeline_id="pipeline-1", llm=llm)

    result = asyncio.run(tutor({}, {}, context))

    assert result.outputs == {"hint": {"level": 1, "text": "Чему равно 2 в кубе?"}}
    assert len(llm.calls) == 1


def test_broken_schema_is_a_clear_error():
    with pytest.raises(FakeLLMError, match="схема ответа записана с ошибкой"):
        complete(FakeLLM([{"level": 1}]), schema={"type": "нет такого типа"})


def test_schema_reference_that_leads_nowhere_is_a_clear_error(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("фейковая модель пошла в сеть за схемой")

    monkeypatch.setattr("urllib.request.urlopen", no_network)

    for ref in ["#/$defs/missing", "http://example.test/schema.json"]:
        with pytest.raises(FakeLLMError, match="ссылка, которая никуда не ведёт"):
            complete(FakeLLM([{"level": 1}]), schema={"$ref": ref})


def task(task_id: str, topic: str, difficulty: int, subject: str = "math") -> Task:
    return Task(
        id=task_id,
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        statement=f"Задача {task_id}",
        check_method=CheckMethod.SHORT_ANSWER,
        answer="1",
    )


BANK = [
    task("log-1", "логарифмы", 1),
    task("log-2", "логарифмы", 2),
    task("deg-1", "степени", 1),
    task("py-1", "циклы", 1, subject="informatics"),
]


def find(store: FakeStore, **conditions) -> list[str]:
    return [found.id for found in asyncio.run(store.find_tasks(**conditions))]


def test_fake_store_fits_the_contract_interface():
    assert isinstance(FakeStore(), PlatformStore)


def test_store_finds_tasks_by_topic_and_difficulty():
    store = FakeStore(BANK)
    assert find(store, topic="логарифмы") == ["log-1", "log-2"]
    assert find(store, difficulty=1) == ["log-1", "deg-1", "py-1"]
    assert find(store, topic="логарифмы", difficulty=2) == ["log-2"]
    assert find(store, subject="informatics") == ["py-1"]


def test_store_without_conditions_gives_all_tasks():
    assert find(FakeStore(BANK)) == ["log-1", "log-2", "deg-1", "py-1"]


def test_nothing_found_is_an_empty_list_not_an_error():
    assert find(FakeStore(BANK), topic="интегралы") == []


def test_store_gives_one_task_by_id():
    store = FakeStore(BANK)
    assert asyncio.run(store.get_task("deg-1")) == BANK[2]
    assert asyncio.run(store.get_task("нет-такой")) is None


def test_block_gets_the_store_through_context():
    """Так подделкой хранилища пользуется тест блока: кладёт её в `context.store`."""

    async def take_task(inputs, config, context: RunContext) -> Done:
        found = await context.store.find_tasks(
            topic=config["topic"], difficulty=config["difficulty"]
        )
        if not found:
            return Done(outcome="empty")
        return Done(outputs={"task": found[0].model_dump(mode="json")})

    context = RunContext(
        run_id="run-1", node_id="take_task", pipeline_id="pipeline-1", store=FakeStore(BANK)
    )

    result = asyncio.run(take_task({}, {"topic": "логарифмы", "difficulty": 2}, context))
    assert result.outputs["task"]["id"] == "log-2"

    result = asyncio.run(take_task({}, {"topic": "интегралы", "difficulty": 1}, context))
    assert result.outcome == "empty"
