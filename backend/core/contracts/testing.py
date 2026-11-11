"""Подделки служб для тестов: ИИ-модель и хранилище платформы (ADR 0006, ADR 0012, ADR 0014).

Блок не видит ни слой моделей `backend/llm/`, ни базу, поэтому подделки лежат рядом с
контрактом: подключить их может и тест ядра, и тест любого блока. Фейковая модель ничего не
отправляет в сеть — отвечает тем, что заранее написал автор теста, и запоминает, о чём её
спросили. Подделка хранилища держит задачи, файлы, результаты учеников и опубликованные
результаты в памяти.

Это вспомогательный файл: моделей контракта он не меняет.
"""

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import JsonValue
from referencing import Registry
from referencing.exceptions import Unresolvable

from backend.core.contracts.interfaces import LLMMessage, LLMResponse, StudentResults
from backend.core.contracts.ports import FileKind, FileRef, Task

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


@dataclass(frozen=True)
class PublishedResult:
    """Результат, который блок опубликовал через подделку хранилища (ADR 0026)."""

    id: str
    key: str
    title: str
    content: JsonValue
    student_id: str | None


class FakeStore:
    """Подделка с интерфейсом `PlatformStore`: данные одного преподавателя в памяти.

    Тест кладёт сюда задачи, которые в платформе были бы подтверждёнными задачами
    преподавателя этого запуска. Ищет так же, как настоящее хранилище: по совпадению условий,
    в том порядке, в каком задачи переданы. Файлы передаются парами «описание — содержимое»
    и находятся по номеру из описания (ADR 0023). `students` — номера учеников этого
    преподавателя: только им можно адресовать результат.

    Записи ведут себя как в настоящем хранилище (ADR 0026): сохранённая задача и файл сразу
    видны через чтение, результат попадает в `published`, а повтор того же ключа возвращает
    уже сохранённую запись и второй не создаёт. Одна подделка — это хранилище одного узла
    одного запуска: настоящее хранилище тоже создаётся на узел, поэтому одинаковые ключи
    в разных узлах там дают разные записи, а в общей подделке — одну.

    `results` — результаты учеников для `find_results` (ADR 0031). Подделка отбрасывает
    работы раньше `since`, а число подсказок отдаёт как есть: журнала, по которому их
    считать, у неё нет. Ученики из `results` тоже считаются учениками преподавателя.
    """

    def __init__(
        self,
        tasks: Iterable[Task] = (),
        files: Iterable[tuple[FileRef, bytes]] = (),
        students: Iterable[str] = (),
        results: Iterable[StudentResults] = (),
    ) -> None:
        self.tasks = list(tasks)
        self.files = {ref.id: (ref, content) for ref, content in files}
        self.results = list(results)
        self.students = set(students) | {found.student_id for found in self.results}
        self.published: list[PublishedResult] = []
        self._written: dict[tuple[str, str], Any] = {}

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

    async def get_file(self, file_id: str) -> FileRef | None:
        found = self.files.get(file_id)
        return None if found is None else found[0]

    async def read_file(self, file_id: str) -> bytes | None:
        found = self.files.get(file_id)
        return None if found is None else found[1]

    async def find_results(self, *, since: datetime) -> list[StudentResults]:
        if since.tzinfo is None:
            raise ValueError("время `since` нужно с часовым поясом")
        return [
            found.model_copy(
                update={"works": [work for work in found.works if work.submitted_at >= since]}
            )
            for found in sorted(self.results, key=lambda found: found.name)
        ]

    async def save_task(self, task: Task, *, key: str) -> Task:
        if ("task", key) not in self._written:
            saved = task.model_copy(update={"id": f"saved-task-{len(self._written) + 1}"})
            self.tasks.append(saved)
            self._written["task", key] = saved
        return self._written["task", key]

    async def save_file(
        self, *, key: str, name: str, kind: FileKind, media_type: str, content: bytes
    ) -> FileRef:
        if ("file", key) not in self._written:
            ref = FileRef(
                id=f"saved-file-{len(self._written) + 1}",
                name=name,
                kind=kind,
                media_type=media_type,
                size=len(content),
            )
            self.files[ref.id] = (ref, content)
            self._written["file", key] = ref
        return self._written["file", key]

    async def publish_result(
        self, *, key: str, title: str, content: JsonValue, student_id: str | None = None
    ) -> str:
        if student_id is not None and student_id not in self.students:
            raise ValueError("ученик не найден")
        if ("result", key) not in self._written:
            result = PublishedResult(
                id=f"result-{len(self._written) + 1}",
                key=key,
                title=title,
                content=content,
                student_id=student_id,
            )
            self.published.append(result)
            self._written["result", key] = result
        return self._written["result", key].id
