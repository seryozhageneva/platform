"""Типы портов: правило совместимости и формы встроенных значений."""

import re

import pytest
from pydantic import ValidationError

from backend.core.contracts.ports import (
    VALUE_MODELS,
    Answer,
    DataType,
    Hint,
    OutputPort,
    PortType,
    can_connect,
    value_problems,
)


def kind(text: str) -> DataType:
    """Короткая запись типа для таблицы: `Task`, `Data<summary>`, `Task[]`."""
    name, of, many = re.fullmatch(r"(\w+)(?:<(\w+)>)?(\[\])?", text).groups()
    return DataType(type=name, of=of, is_list=bool(many))


# Выход, вход, стыкуются ли.
CASES = [
    ("Task", "Task", True),
    ("Task", "Answer", False),
    ("Data<summary>", "Data<summary>", True),
    ("Data<summary>", "Data<submission>", False),
    ("Data<summary>", "Data<submission>[]", False),
    # Вход «Data без уточнения» принимает любое значение, в том числе список.
    ("Text", "Data", True),
    ("Data<summary>", "Data", True),
    ("Task[]", "Data", True),
    # Вход «список Data без уточнения» принимает любой список, но не одно значение.
    ("File[]", "Data[]", True),
    ("Data<submission>[]", "Data[]", True),
    ("File", "Data[]", False),
    # «Список или один» у типизированного входа должен совпасть.
    ("Task[]", "Task", False),
    ("Task", "Task[]", False),
    ("Task[]", "Task[]", True),
    # В обратную сторону «любое» не работает: неизвестно что нельзя подать на вход Task.
    ("Data", "Task", False),
    ("Data", "Data<summary>", False),
]


@pytest.mark.parametrize(("source", "target", "expected"), CASES)
def test_can_connect(source, target, expected):
    assert can_connect(kind(source), kind(target)) is expected


def test_refinement_only_for_data():
    with pytest.raises(ValidationError, match="только у типа Data"):
        DataType(type="Task", of="summary")


def test_computed_output_is_declared_as_plain_data():
    OutputPort(name="approved", title="Подтверждённое", type="Data", same_as="items")
    with pytest.raises(ValidationError, match="тип вычисляется"):
        OutputPort(name="approved", title="Подтверждённое", type="Task", same_as="items")
    with pytest.raises(ValidationError, match="что-то одно"):
        OutputPort(name="x", title="x", type="Data", same_as="items", from_config="result")


def test_port_schema_must_be_json_schema():
    with pytest.raises(ValidationError, match="это не JSON Schema"):
        OutputPort(name="x", title="x", type="Data", of="summary", schema={"type": "нет такого"})
    with pytest.raises(ValidationError, match="только вместе с `of`"):
        OutputPort(name="x", title="x", type="Data", schema={"type": "object"})


def test_every_type_except_data_has_a_value_model():
    assert set(VALUE_MODELS) == set(PortType) - {PortType.DATA}


TASK = {
    "id": "t1",
    "subject": "math",
    "topic": "логарифмы",
    "difficulty": 2,
    "statement": "Вычисли $\\log_2 8$.",
    "check_method": "short_answer",
    "answer": "3",
}


def test_value_problems():
    assert value_problems(kind("Task"), TASK) == []
    assert value_problems(kind("Task[]"), [TASK, TASK]) == []

    problems = value_problems(kind("Task"), {**TASK, "check_method": "устно"})
    assert len(problems) == 1 and problems[0].startswith("check_method: недопустимое значение")

    assert value_problems(kind("Task[]"), TASK) == ["ожидался список Task, а пришло не списком"]
    assert value_problems(kind("Task[]"), [TASK, {}])[0].startswith("элемент 1: id:")


def test_value_problems_for_data_use_port_schema():
    schema = {"type": "object", "required": ["student_id"]}
    assert value_problems(kind("Data<lesson_result>"), {"student_id": "s1"}, schema) == []
    assert value_problems(kind("Data<lesson_result>"), {}, schema) != []
    # Без схемы проверять нечем: значение принимается как есть.
    assert value_problems(kind("Data<lesson_result>"), {}) == []


def test_answer_and_hint_rules():
    Answer(task_id="t1", form="formula", text="\\frac{1}{2}")
    with pytest.raises(ValidationError, match="должен быть файл"):
        Answer(task_id="t1", form="photo")
    with pytest.raises(ValidationError, match="должен быть текст"):
        Answer(task_id="t1", form="text")
    with pytest.raises(ValidationError):
        Hint(task_id="t1", level=4, text="Ответ: 3")
