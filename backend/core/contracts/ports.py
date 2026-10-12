"""Порты блока: виды данных, формы встроенных значений и правило совместимости.

Спецификация — docs/contract.md, раздел «Порты»; решение — ADR 0004.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, ValidationError, model_validator

from backend.core.contracts.base import NAME, Strict, explain


class PortType(StrEnum):
    """Восемь видов данных, которые ходят между блоками."""

    EVENT = "Event"
    DATA = "Data"
    FILE = "File"
    TEXT = "Text"
    TASK = "Task"
    ANSWER = "Answer"
    VERDICT = "Verdict"
    HINT = "Hint"


class DataType(Strict):
    """Тип данных на порту: вид, уточнение (только у Data) и «список или один элемент»."""

    type: PortType
    of: str | None = Field(None, pattern=NAME)
    is_list: bool = Field(False, alias="list")

    @model_validator(mode="after")
    def _of_only_for_data(self) -> Self:
        if self.of is not None and self.type is not PortType.DATA:
            raise ValueError("уточнение `of` бывает только у типа Data")
        return self

    def element(self) -> "DataType":
        """Тип одного элемента (для списка) или сам тип без полей порта."""
        return DataType(type=self.type, of=self.of)

    def as_list(self) -> "DataType":
        return DataType(type=self.type, of=self.of, is_list=True)

    def label(self) -> str:
        """Запись для сообщений об ошибках: `Task`, `Data<submission>`, `список Task`."""
        name = f"{self.type.value}<{self.of}>" if self.of else self.type.value
        return f"список {name}" if self.is_list else name


def can_connect(source: DataType, target: DataType) -> bool:
    """Можно ли подать выход `source` на вход `target`.

    Вход `Data` без уточнения принимает любое значение, а если он объявлен списком — любой
    список. Во всех остальных случаях вид, уточнение и «список или один» должны совпасть.
    """
    any_data = target.type is PortType.DATA and target.of is None
    if any_data and not target.is_list:
        return True
    if source.is_list != target.is_list:
        return False
    return any_data or (source.type is target.type and source.of == target.of)


def check_json_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"это не JSON Schema: {error.message}") from error


class _Port(DataType):
    name: str = Field(pattern=NAME)
    title: str
    # Для Data с уточнением: как выглядит один элемент. Совместимость проверяется по имени
    # уточнения, а схема нужна редактору и автору соседнего блока.
    json_schema: dict[str, Any] | None = Field(None, alias="schema")

    @model_validator(mode="after")
    def _schema_only_for_refined_data(self) -> Self:
        if self.json_schema is not None:
            if self.of is None:
                raise ValueError("`schema` описывает уточнение и нужна только вместе с `of`")
            check_json_schema(self.json_schema)
        return self


class InputPort(_Port):
    """Вход блока. Необязательный вход может остаться без данных."""

    required: bool = True


class OutputPort(_Port):
    """Выход блока.

    У универсальных блоков тип выхода вычисляется для каждого узла: `same_as` — повторяет
    тип того, что подано на указанный вход; `from_config` — записан в указанной настройке.
    """

    same_as: str | None = Field(None, pattern=NAME)
    from_config: str | None = Field(None, pattern=NAME)

    @model_validator(mode="after")
    def _computed_type_is_plain_data(self) -> Self:
        if self.same_as and self.from_config:
            raise ValueError("укажи что-то одно: `same_as` или `from_config`")
        if (self.same_as or self.from_config) and (
            self.type is not PortType.DATA or self.of or self.is_list
        ):
            raise ValueError(
                "у выхода с `same_as` или `from_config` тип объявляется как Data "
                "без уточнения и без `list`: настоящий тип вычисляется для узла"
            )
        return self


# --- Формы встроенных значений -----------------------------------------------------------


class TriggerType(StrEnum):
    """Способы запуска пайплайна."""

    MANUAL = "manual"
    STUDENT = "student"
    SCHEDULE = "schedule"
    MOODLE_EVENT = "moodle_event"


class Event(Strict):
    """Что запустило пайплайн. Имён людей здесь нет — только идентификаторы."""

    trigger: TriggerType
    occurred_at: datetime
    student_id: str | None = None
    assignment_id: str | None = None
    payload: dict[str, Any] = {}


class FileKind(StrEnum):
    DOCUMENT = "document"
    CODE = "code"
    IMAGE = "image"
    OTHER = "other"


class FileRef(Strict):
    """Тип `File`: ссылка на файл в хранилище, а не его содержимое."""

    id: str
    name: str
    kind: FileKind
    media_type: str
    size: int | None = Field(None, ge=0)
    # Чья это работа; по этому полю Получатель понимает, кому адресован результат.
    student_id: str | None = None
    meta: dict[str, Any] = {}


class Text(Strict):
    text: str
    source: FileRef | None = None


class CheckMethod(StrEnum):
    """Способ проверки записан в самой задаче."""

    SHORT_ANSWER = "short_answer"
    CODE = "code"
    LONG_ANSWER = "long_answer"


class Task(Strict):
    id: str
    subject: str
    topic: str
    difficulty: int = Field(ge=1)
    statement: str
    check_method: CheckMethod
    answer: str | None = None
    solution: str | None = None
    tests: str | None = None
    rubric: str | None = None


class AnswerForm(StrEnum):
    TEXT = "text"
    FORMULA = "formula"
    CODE = "code"
    PHOTO = "photo"


class Answer(Strict):
    task_id: str
    form: AnswerForm
    text: str | None = None
    file: FileRef | None = None

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if self.form is AnswerForm.PHOTO and self.file is None:
            raise ValueError("у ответа-фото должен быть файл")
        if self.form is not AnswerForm.PHOTO and self.text is None:
            raise ValueError("у ответа должен быть текст")
        return self


class Verdict(Strict):
    correct: bool
    task_id: str | None = None
    score: float | None = None
    max_score: float | None = None
    comment: str | None = None
    # Вердикт ИИ: урок идёт дальше, а преподаватель позже может исправить оценку.
    preliminary: bool = False


class Hint(Strict):
    task_id: str
    level: int = Field(ge=1, le=3)
    text: str


VALUE_MODELS: dict[PortType, type[Strict]] = {
    PortType.EVENT: Event,
    PortType.FILE: FileRef,
    PortType.TEXT: Text,
    PortType.TASK: Task,
    PortType.ANSWER: Answer,
    PortType.VERDICT: Verdict,
    PortType.HINT: Hint,
}


def value_problems(
    kind: DataType, value: Any, json_schema: dict[str, Any] | None = None
) -> list[str]:
    """Чем значение не подходит под тип порта; пустой список — подходит."""
    if kind.is_list:
        if not isinstance(value, list):
            return [f"ожидался {kind.label()}, а пришло не списком"]
        return [
            f"элемент {index}: {problem}"
            for index, item in enumerate(value)
            for problem in value_problems(kind.element(), item, json_schema)
        ]
    model = VALUE_MODELS.get(kind.type)
    if model is not None:
        try:
            model.model_validate(value)
        except ValidationError as error:
            return explain(error)
    elif json_schema is not None:
        return [e.message for e in Draft202012Validator(json_schema).iter_errors(value)]
    return []
