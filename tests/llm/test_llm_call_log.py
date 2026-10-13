"""Стыковка слоя моделей с журналом вызовов в базе.

Слой и база друг друга не подключают (правило 5 в `.importlinter`): слой знает только, что у
журнала есть метод `record`. Здесь они впервые встречаются — как их соединит слой сборки.
"""

import asyncio
import inspect

from llm_doubles import ScriptedProvider
from sqlalchemy import select

from backend.core.contracts.interfaces import LLMMessage
from backend.llm.client import CallLog, PlatformLLM
from backend.llm.providers import LLMError
from backend.models.llm_calls import LLMCallRepository
from backend.models.tables import LLMCallRow

ASK = [LLMMessage(role="user", content="Сколько будет 2 + 2?")]


def rows(sessions) -> list[LLMCallRow]:
    async def read():
        async with sessions() as session:
            return list(await session.scalars(select(LLMCallRow).order_by(LLMCallRow.id)))

    return asyncio.run(read())


def test_repository_takes_exactly_what_the_layer_writes():
    """Имена аргументов совпадают: добавили поле с одной стороны — тест напомнит о другой."""
    expected = set(inspect.signature(CallLog.record).parameters) - {"self"}

    assert set(inspect.signature(LLMCallRepository.record).parameters) - {"self"} == expected


def test_call_made_through_the_layer_lands_in_the_database(sessions):
    llm = PlatformLLM(ScriptedProvider("4"), call_log=LLMCallRepository(sessions))

    reply = asyncio.run(llm.complete(ASK))

    (row,) = rows(sessions)
    assert reply.text == "4"
    assert (row.provider, row.model) == ("scripted", "scripted-1")
    assert (row.input_tokens, row.output_tokens) == (12, 5)
    assert row.latency_ms >= 0
    assert row.error is None and row.run_id is None


def test_failed_call_lands_in_the_database_too(sessions):
    provider = ScriptedProvider(LLMError("timeout", "GigaChat не ответил за 60 секунд"))
    llm = PlatformLLM(provider, call_log=LLMCallRepository(sessions))

    try:
        asyncio.run(llm.complete(ASK))
    except LLMError:
        pass

    assert [row.error for row in rows(sessions)] == ["timeout"]


def test_call_is_not_lost_when_the_run_is_unknown_to_the_database(sessions, caplog):
    """Журнал не смог записать вызов — блок всё равно получает ответ модели."""
    llm = PlatformLLM(ScriptedProvider("4"), call_log=LLMCallRepository(sessions))

    reply = asyncio.run(llm.bound(run_id="run-1", node_id="tutor").complete(ASK))

    assert reply.text == "4"
    assert rows(sessions) == []
    assert "вызов модели не записан в журнал (ValueError)" in caplog.text
