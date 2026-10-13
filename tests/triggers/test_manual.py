"""Проверка значений параметров перед запуском (ADR 0011 оставил её задаче 08).

Базы, блоков и модели здесь нет: проверяется только правило «значение подходит под тип».
"""

import pytest

from backend.core.contracts.pipeline import parse_pipeline
from backend.triggers.manual import param_problems


def pipeline_with(*params: dict):
    return parse_pipeline(
        {
            "format": 1,
            "id": "params_only",
            "name": "Только параметры",
            "params": list(params),
            "nodes": [{"id": "start", "type": "trigger", "launches": [{"type": "manual"}]}],
        }
    )


TOPIC = {"name": "topic", "title": "Тема", "type": "string"}
COUNT = {"name": "count", "title": "Число задач", "type": "integer", "default": 3}
SHARE = {"name": "share", "title": "Доля", "type": "number"}
HINTS = {"name": "hints", "title": "Подсказки", "type": "boolean", "default": True}


@pytest.mark.parametrize(
    ("param", "value"),
    [
        (TOPIC, "Логарифмы"),
        (COUNT, 5),
        (SHARE, 0.5),
        # Целое годится и там, где ждут число.
        (SHARE, 1),
        (HINTS, False),
    ],
)
def test_fitting_value_is_accepted(param, value):
    assert param_problems(pipeline_with(param), {param["name"]: value}) == []


@pytest.mark.parametrize(
    ("param", "value", "expected"),
    [
        (TOPIC, 5, "строка"),
        (COUNT, "5", "целое число"),
        (COUNT, 2.5, "целое число"),
        # «Да» — не число, хотя Python считает True единицей.
        (COUNT, True, "целое число"),
        (SHARE, "половина", "число"),
        (SHARE, True, "число"),
        (HINTS, 1, "да или нет (true/false)"),
        # «Не число» и бесконечность база не хранит.
        (SHARE, float("inf"), "число"),
    ],
)
def test_value_of_a_wrong_type_is_explained(param, value, expected):
    problems = param_problems(pipeline_with(param), {param["name"]: value})

    assert problems == [
        f"параметр «{param['name']}» ({param['title']}): ожидается {expected}, а получено {value!r}"
    ]


def test_default_is_used_when_the_value_is_not_given():
    assert param_problems(pipeline_with(COUNT, HINTS), {}) == []


def test_param_without_a_value_and_a_default_is_reported():
    assert param_problems(pipeline_with(TOPIC, COUNT), {}) == [
        "параметр «topic» (Тема) не заполнен"
    ]


def test_unknown_param_is_reported():
    assert param_problems(pipeline_with(COUNT), {"cuont": 5}) == [
        "у пайплайна нет параметра «cuont»"
    ]
