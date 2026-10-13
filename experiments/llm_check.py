"""Ручная проверка настоящей модели: один обычный вопрос и один вопрос с ответом по схеме.

Запуск из корня репозитория:  uv run python -m experiments.llm_check

Это не тест: скрипт идёт в сеть и тратит токены, поэтому запускается только вручную.
Вопрос выдуманный, данных учеников здесь нет. Ключ берётся из `.env` и на экран не выводится.
"""

import asyncio
import sys
from typing import Any

from backend.core.contracts.interfaces import LLMMessage
from backend.llm.factory import make_llm
from backend.llm.providers import LLMError

QUESTION = "Сколько будет 2 + 2?"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class PrintedCallLog:
    """Вместо базы: печатает то, что слой записал бы в журнал вызовов."""

    async def record(self, **fields: Any) -> None:
        error = fields["error"] or "нет"
        print(
            f"  провайдер: {fields['provider']}, модель: {fields['model']}, "
            f"токены: {fields['input_tokens']} на входе и {fields['output_tokens']} на выходе, "
            f"задержка: {fields['latency_ms']} мс, ошибка: {error}"
        )


async def main() -> int:
    try:
        llm = make_llm(call_log=PrintedCallLog())
    except LLMError as error:
        print(f"Модель не подключена: {error}")
        return 1
    try:
        print(f"1. Обычный вопрос: {QUESTION} Ответь одним числом.")
        reply = await llm.complete(
            [LLMMessage(role="user", content=f"{QUESTION} Ответь одним числом.")]
        )
        print(f"  ответ: {reply.text}")

        print(f"2. Тот же вопрос с ответом по схеме: {QUESTION}")
        reply = await llm.complete([LLMMessage(role="user", content=QUESTION)], schema=SCHEMA)
        print(f"  ответ по схеме: {reply.data}")
    except LLMError as error:
        print(f"Вызов не удался: {error}")
        return 1
    finally:
        await llm.aclose()
    print("Готово: модель отвечает.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
