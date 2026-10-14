"""Подделки служб для тестов: ИИ-модель и хранилище платформы (ADR 0006, ADR 0012, ADR 0014).

Блок не видит ни слой моделей `backend/llm/`, ни базу, поэтому подделки лежат рядом с
контрактом: подключить их может и тест ядра, и тест любого блока. Фейковая модель ничего не
отправляет в сеть — отвечает тем, что заранее написал автор теста, и запоминает, о чём её
спросили. Подделка хранилища держит задачи в памяти.

Это вспомогательный файл: моделей контракта он не меняет.
"""

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from backend.core.contracts.interfaces import LLMMessage, LLMResponse
from backend.core.contracts.ports import Task

# Ответ, заданный в тесте: текст, данные для ответа по схеме или ошибка, с которой модель «упадёт».
FakeReply = str | dict[str, Any] | list[Any] | Exception


class FakeLLMError(AssertionError):
    """Тест и блок разошлись: ответов не хватило или ответ не подходит под схему."""


@dataclass(frozen=True)
class FakeCall:
    """Один вызов фейковой модели — что именно блок у неё спросил."""

    messages: list[LLMMessage]
    schema: dict[str, Any] | None
    model: str | None


class FakeLLM:
    """Подделка с интерфейсом `LLMClient`.

    `replies` выдаются по одному на вызов, по порядку. Когда они кончились, отвечает `default`;
    если и его нет — ошибка: блок обратился к модели чаще, чем ждал тест.
    """

    def __init__(
        self,
        replies: Iterable[FakeReply] = (),
        *,
        default: FakeReply | None = None,
        model: str = "fake",
    ) -> None:
        self._replies = deque(replies)
        self._default = default
        self._model = model
        self.calls: list[FakeCall] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        self.calls.append(FakeCall(list(messages), schema, model))
        reply = self._next()
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResponse(
            text=text,
            data=None if schema is None else _by_schema(reply, schema),
            model=model or self._model,
            # Настоящие токены считает провайдер; здесь для простоты это число слов.
            input_tokens=sum(len(message.content.split()) for message in messages),
            output_tokens=len(text.split()),
        )

    def _next(self) -> FakeReply:
        if self._replies:
            return self._replies.popleft()
        if self._default is not None:
            return self._default
        raise FakeLLMError(
            f"фейковой модели не хватило ответов: это вызов № {len(self.calls)}, "
            "а ответов в тесте задано меньше"
        )


def _by_schema(reply: str | dict[str, Any] | list[Any], schema: dict[str, Any]) -> Any:
    """Данные ответа по схеме. Не подошли или схема с ошибкой — понятная ошибка теста."""
    if isinstance(reply, str):
        try:
            data = json.loads(reply)
        except json.JSONDecodeError:
            raise FakeLLMError(
                f"блок просил ответ по схеме, а в тесте задан текст не в формате JSON: «{reply}»"
            ) from None
    else:
        data = reply
    try:
        Draft202012Validator.check_schema(schema)
        # Пустой реестр: за схемами по сети библиотека не ходит.
        validator = Draft202012Validator(schema, registry=Registry())
        problems = [error.message for error in validator.iter_errors(data)]
    except SchemaError as error:
        raise FakeLLMError(f"схема ответа записана с ошибкой: {error.message}") from None
    except Unresolvable:
        raise FakeLLMError(
            "в схеме ответа есть ссылка, которая никуда не ведёт или ведёт на внешний адрес"
        ) from None
    if problems:
        raise FakeLLMError(
            "ответ фейковой модели не подходит под схему: " + "; ".join(sorted(problems))
        )
    return data


class FakeStore:
    """Подделка с интерфейсом `PlatformStore`: банк задач одного преподавателя в памяти.

    Тест кладёт сюда задачи, которые в платформе были бы подтверждёнными задачами
    преподавателя этого запуска. Ищет так же, как настоящее хранилище: по совпадению условий,
    в том порядке, в каком задачи переданы.
    """

    def __init__(self, tasks: Iterable[Task] = ()) -> None:
        self.tasks = list(tasks)

    async def find_tasks(
        self,
        *,
        topic: str | None = None,
        difficulty: int | None = None,
        subject: str | None = None,
    ) -> list[Task]:
        return [
            task
            for task in self.tasks
            if (topic is None or task.topic == topic)
            and (difficulty is None or task.difficulty == difficulty)
            and (subject is None or task.subject == subject)
        ]

    async def get_task(self, task_id: str) -> Task | None:
        return next((task for task in self.tasks if task.id == task_id), None)
