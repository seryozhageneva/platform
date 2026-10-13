"""Слой моделей: ответ по схеме, понятные ошибки и запись каждого вызова в журнал."""

import asyncio
import json

import pytest
from llm_doubles import ScriptedProvider

from backend.core.contracts.interfaces import LLMClient, LLMMessage
from backend.llm.client import SCHEMA_REQUEST, PlatformLLM
from backend.llm.providers import LLMError, StubProvider

ASK = [LLMMessage(role="user", content="Сколько будет 2 + 2?")]
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
}


def complete(llm: PlatformLLM, messages=ASK, **options):
    return asyncio.run(llm.complete(messages, **options))


def test_layer_fits_the_contract_interface():
    assert isinstance(PlatformLLM(ScriptedProvider()), LLMClient)


def test_plain_call_returns_text_model_and_tokens():
    reply = complete(PlatformLLM(ScriptedProvider("4")))

    assert reply.text == "4"
    assert reply.data is None
    assert reply.model == "scripted-1"
    assert (reply.input_tokens, reply.output_tokens) == (12, 5)


def test_plain_call_passes_messages_unchanged():
    provider = ScriptedProvider("4")

    complete(PlatformLLM(provider))

    assert provider.requests == [(ASK, None)]


def test_block_can_ask_for_another_model():
    provider = ScriptedProvider("4")

    reply = complete(PlatformLLM(provider), model="scripted-max")

    assert provider.requests[0][1] == "scripted-max"
    assert reply.model == "scripted-max"


def test_schema_request_is_added_as_a_system_message():
    provider = ScriptedProvider('{"answer": 4}')

    complete(PlatformLLM(provider), schema=SCHEMA)

    sent, _ = provider.requests[0]
    assert [message.role for message in sent] == ["system", "user"]
    assert sent[0].content == SCHEMA_REQUEST + json.dumps(SCHEMA, ensure_ascii=False)
    assert sent[1] == ASK[0]


def test_schema_request_joins_the_existing_system_message():
    """Системное сообщение у провайдеров одно и первое: второе добавлять нельзя."""
    provider = ScriptedProvider('{"answer": 4}')
    messages = [LLMMessage(role="system", content="Ты учитель математики."), *ASK]

    complete(PlatformLLM(provider), messages, schema=SCHEMA)

    sent, _ = provider.requests[0]
    assert [message.role for message in sent] == ["system", "user"]
    assert sent[0].content.startswith("Ты учитель математики.\n\n" + SCHEMA_REQUEST)
    # Сообщения блока при этом не тронуты.
    assert messages[0].content == "Ты учитель математики."


def test_reply_by_schema_is_parsed_into_data():
    reply = complete(PlatformLLM(ScriptedProvider('{"answer": 4}')), schema=SCHEMA)

    assert reply.data == {"answer": 4}
    assert reply.text == '{"answer": 4}'


def test_json_wrapped_in_a_code_fence_is_parsed_too():
    fenced = 'Вот ответ:\n```json\n{"answer": 4}\n```'

    assert complete(PlatformLLM(ScriptedProvider(fenced)), schema=SCHEMA).data == {"answer": 4}


def test_reply_that_is_not_json_is_a_clear_error():
    with pytest.raises(LLMError, match="не в формате JSON") as caught:
        complete(PlatformLLM(ScriptedProvider("Будет четыре.")), schema=SCHEMA)

    assert caught.value.kind == "not_json"


def test_json_that_does_not_fit_the_schema_is_a_clear_error():
    with pytest.raises(LLMError, match="не подходит под схему") as caught:
        complete(PlatformLLM(ScriptedProvider('{"answer": "четыре"}')), schema=SCHEMA)

    assert caught.value.kind == "schema"


def test_broken_schema_is_reported_before_the_model_is_called():
    provider = ScriptedProvider('{"answer": 4}')

    with pytest.raises(LLMError, match="схема ответа записана с ошибкой"):
        complete(PlatformLLM(provider), schema={"type": "нет такого типа"})

    assert provider.requests == []


def test_provider_error_reaches_the_block_as_is():
    failure = LLMError("network", "нет связи с GigaChat: проверь интернет")

    with pytest.raises(LLMError, match="нет связи с GigaChat") as caught:
        complete(PlatformLLM(ScriptedProvider(failure)))

    assert caught.value is failure


def test_unexpected_error_text_does_not_leak():
    """Текст чужой ошибки наружу не идёт: в нём могут быть адреса и подробности запроса."""
    provider = ScriptedProvider(RuntimeError("https://example.test/?token=secret-value"))

    with pytest.raises(LLMError) as caught:
        complete(PlatformLLM(provider))

    assert caught.value.kind == "provider"
    assert str(caught.value) == "вызов модели не удался (RuntimeError)"


def test_successful_call_is_recorded(call_log):
    complete(PlatformLLM(ScriptedProvider("4"), call_log=call_log))

    (record,) = call_log.records
    latency_ms = record.pop("latency_ms")
    assert isinstance(latency_ms, int) and latency_ms >= 0
    assert record == {
        "provider": "scripted",
        "model": "scripted-1",
        "input_tokens": 12,
        "output_tokens": 5,
        "error": None,
        "run_id": None,
        "node_id": None,
    }


def test_failed_call_is_recorded_with_the_kind_of_failure(call_log):
    provider = ScriptedProvider(LLMError("timeout", "GigaChat не ответил за 60 секунд"))

    with pytest.raises(LLMError):
        complete(PlatformLLM(provider, call_log=call_log), model="scripted-max")

    (record,) = call_log.records
    assert record["error"] == "timeout"
    assert record["model"] == "scripted-max"
    assert (record["input_tokens"], record["output_tokens"]) == (0, 0)


def test_reply_not_by_schema_is_recorded_with_its_tokens(call_log):
    """Модель ответила, токены потрачены — они записаны, хотя ответ не подошёл."""
    with pytest.raises(LLMError):
        complete(PlatformLLM(ScriptedProvider("Будет четыре."), call_log=call_log), schema=SCHEMA)

    (record,) = call_log.records
    assert record["error"] == "not_json"
    assert (record["input_tokens"], record["output_tokens"]) == (12, 5)


def test_record_has_no_text_of_the_request_or_the_reply(call_log):
    with pytest.raises(LLMError):
        complete(
            PlatformLLM(ScriptedProvider('{"answer": "секретный ответ"}'), call_log=call_log),
            schema=SCHEMA,
        )

    written = json.dumps(call_log.records, ensure_ascii=False)
    assert "секретный ответ" not in written
    assert "Сколько будет" not in written


def test_bound_layer_marks_calls_with_run_and_node(call_log):
    llm = PlatformLLM(ScriptedProvider("4"), call_log=call_log)

    complete(llm.bound(run_id="run-1", node_id="tutor"))
    complete(llm)

    assert [(record["run_id"], record["node_id"]) for record in call_log.records] == [
        ("run-1", "tutor"),
        (None, None),
    ]


def test_broken_call_log_does_not_break_the_call(caplog):
    class BrokenCallLog:
        async def record(self, **fields):
            raise RuntimeError("база недоступна")

    reply = complete(PlatformLLM(ScriptedProvider("4"), call_log=BrokenCallLog()))

    assert reply.text == "4"
    assert "вызов модели не записан в журнал (RuntimeError)" in caplog.text


def test_stub_provider_answers_without_network(call_log):
    reply = complete(PlatformLLM(StubProvider(), call_log=call_log))

    assert "заглушк" in reply.text
    assert reply.model == "fake"
    assert call_log.records[0]["provider"] == "fake"


@pytest.mark.parametrize(
    "text",
    [
        'Ответ: {"answer": 4}',
        '{"answer": 4}\n\nПояснение: два плюс два — четыре.',
        '```JSON\n{"answer": 4}\n```',
        'Смотри [решение] ниже: {"answer": 4}',
    ],
)
def test_json_is_found_among_extra_words(text):
    assert complete(PlatformLLM(ScriptedProvider(text)), schema=SCHEMA).data == {"answer": 4}


def test_error_about_the_schema_does_not_quote_the_reply():
    """В тексте ошибки — место и правило, но не слова из ответа модели."""
    provider = ScriptedProvider('{"answer": "секретный ответ", "лишнее поле": 1}')
    strict = {**SCHEMA, "additionalProperties": False}

    with pytest.raises(LLMError) as caught:
        complete(PlatformLLM(provider), schema=strict)

    text = str(caught.value)
    assert "$.answer — правило «type»" in text
    assert "секретный ответ" not in text and "лишнее поле" not in text


def test_schema_may_not_point_outside_itself(monkeypatch, call_log):
    """Ссылка наружу заставила бы сервер скачивать схему по чужому адресу."""

    def no_network(*args, **kwargs):
        raise AssertionError("слой пошёл в сеть за схемой")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    provider = ScriptedProvider('{"answer": 4}')

    with pytest.raises(LLMError, match="ссылается на другой файл или адрес") as caught:
        complete(
            PlatformLLM(provider, call_log=call_log),
            schema={"$ref": "http://example.test/schema.json"},
        )

    assert caught.value.kind == "bad_schema"
    assert provider.requests == [] and call_log.records == []


def test_broken_reference_inside_the_schema_is_reported_before_the_call():
    """Ошибка в схеме — вина блока, а не модели: токены на неё не тратятся."""
    provider = ScriptedProvider('{"answer": 4}')
    schema = {"type": "object", "properties": {"answer": {"$ref": "#/$defs/missing"}}}

    with pytest.raises(LLMError, match="«#/\\$defs/missing» в схеме ответа никуда не ведёт"):
        complete(PlatformLLM(provider), schema=schema)

    assert provider.requests == []


def test_reference_inside_the_schema_works():
    schema = {
        "type": "object",
        "properties": {"answer": {"$ref": "#/$defs/number"}},
        "$defs": {"number": {"type": "integer"}},
    }

    assert complete(PlatformLLM(ScriptedProvider('{"answer": 4}')), schema=schema).data == {
        "answer": 4
    }
    with pytest.raises(LLMError, match="правило «type»"):
        complete(PlatformLLM(ScriptedProvider('{"answer": "четыре"}')), schema=schema)


def test_broken_reference_by_label_is_blamed_on_the_schema(call_log):
    """Ссылку по метке до вызова не проверить; после вызова виновата всё равно схема."""
    provider = ScriptedProvider('{"answer": 4}')

    with pytest.raises(LLMError) as caught:
        complete(PlatformLLM(provider, call_log=call_log), schema={"$ref": "#missing"})

    assert caught.value.kind == "bad_schema"
    assert call_log.records[0]["error"] == "bad_schema"
