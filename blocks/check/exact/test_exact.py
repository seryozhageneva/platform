"""Блок «Проверка: по эталону»: без базы, без модели и без хранилища.

Критерий задачи 11 — 20 пар «ответ — эталон» в эквивалентных формах. Задачи и ответы выдуманные.
"""

import asyncio
import time
from pathlib import Path

import pytest

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import AnswerForm, CheckMethod, Task, Verdict
from backend.core.contracts.run import Done, RunContext, result_problems
from blocks.check.exact import run

HERE = Path(__file__).parent
EXAMPLE = HERE.parents[2] / "docs" / "examples" / "manifests" / "check.exact.yaml"
MANIFEST = load_manifest(HERE / "block.yaml")

# Ответ ученика, эталон из задачи. Обе стороны читаются одинаково: эталон тоже можно писать
# обычным текстом или LaTeX.
EQUIVALENT = [
    ("x + 1", "1 + x"),
    ("2(x+1)", "2x + 2"),
    ("0,5", "1/2"),
    ("0.25", r"\frac{1}{4}"),
    (r"2\sqrt{2}", "sqrt(8)"),
    ("x**2", "x^2"),
    ("x·x", "x^2"),
    ("  x   ^ 2  ", "x^2"),
    ("x = 3", "3"),
    ("3; 2", "2; 3"),
    ("x_1 = -3, x_2 = 2", "2; -3"),
    (r"\sin^2 x + \cos^2 x", "1"),
    ("3", r"\log_2 8"),
    ("lg 100", "2"),
    ("(x - 1)(x + 1)", "x^2 - 1"),
    (r"\frac{\pi}{2}", "pi/2"),
    ("√2/2", r"\frac{1}{\sqrt{2}}"),
    ("e^(2x)", r"\exp(x)^2"),
    ("tg x", "sin x / cos x"),
    (r"\left(a+b\right)^{2}", "a^2 + 2ab + b^2"),
]

DIFFERENT = [
    ("-x", "x"),
    ("1.41", "sqrt(2)"),
    ("0.333", "1/3"),
    ("2", "2; 3"),
    ("2; 3; 4", "2; 3"),
    ("2; 2", "2; 3"),
    ("y + 1", "x + 1"),
    ("|x|", "x"),
    ("x^2 + 1", "(x + 1)^2"),
    ("sin x", "cos x"),
    # Приближённый ответ с калькулятора — не эталон, сколько бы цифр ни совпало.
    ("3.1415926535898", "pi"),
    ("0.3333333333333", "1/3"),
    ("1.4142135623731", r"\sqrt{2}"),
    ("2", "2.0000000000001"),
    ("1000000000000001", "1000000000000000"),
    ("0.3333333333333x", "x/3"),
]

UNREADABLE = [
    "2x+",
    "абв",
    "(x + 1",
    "2 3",
    "x = y = 2",
    "1/0",
    r"\int x\,dx",
]

ATTACKS = [
    "__import__('os').system('ls')",
    "x.__class__",
    "eval('1')",
    "x" * 300,
    "9^9^9^9",
    "(10^100)^100",
    "x^(x^(x^(x^2)))",
    r"10^{10^{10}}",
    # Короткие, но тяжёлые для упрощения: раскрытие скобок дало бы тысячи слагаемых.
    "(x+y+z+1)^100",
    "(sin x + cos x)^100 - (1 + sin(2x))^50 + 3",
]

# Корень нечётной степени из отрицательного числа — действительный, как в школе.
ODD_ROOTS = [
    (r"\sqrt[3]{-8}", "-2"),
    ("-2", r"\sqrt[3]{-8}"),
    (r"\sqrt[3]{-27} + 1", "-2"),
    (r"-\sqrt[3]{x}", r"\sqrt[3]{-x}"),
    ("root_3(-8)", "-2"),
]


def task(answer: str | None = "3", task_id: str = "task-1") -> Task:
    return Task(
        id=task_id,
        subject="math",
        topic="algebra",
        difficulty=1,
        statement="Упростите выражение.",
        check_method=CheckMethod.SHORT_ANSWER,
        answer=answer,
    )


def check(answer: str, reference: str | None = "3", form: AnswerForm = AnswerForm.TEXT) -> Done:
    the_task = task(reference)
    inputs = {
        "task": the_task.model_dump(mode="json"),
        "answer": {"task_id": the_task.id, "form": form.value, "text": answer},
    }
    context = RunContext(run_id="run-1", node_id="check_exact", pipeline_id="scenario_1_training")
    result = asyncio.run(run(inputs, {}, context))
    assert result_problems(MANIFEST, result) == []
    return result


def verdict(result: Done) -> Verdict:
    return Verdict.model_validate(result.outputs["verdict"])


@pytest.mark.parametrize(("answer", "reference"), EQUIVALENT)
def test_equivalent_forms_are_correct(answer, reference):
    result = check(answer, reference)

    assert result.outcome == "correct"
    assert verdict(result).correct


def test_the_criterion_has_twenty_pairs():
    assert len(EQUIVALENT) == 20


@pytest.mark.parametrize(("answer", "reference"), DIFFERENT)
def test_different_answers_are_wrong(answer, reference):
    result = check(answer, reference)

    assert result.outcome == "wrong"
    assert not verdict(result).correct
    assert verdict(result).comment == "Ответ не совпадает с эталоном."


@pytest.mark.parametrize("answer", UNREADABLE)
def test_unreadable_answer_is_wrong_and_does_not_break_the_run(answer):
    result = check(answer, "2")

    assert result.outcome == "wrong"
    assert verdict(result).comment == "Не удалось разобрать ответ: проверьте запись."
    assert result.events[0].data["readable"] is False


@pytest.mark.parametrize("answer", ATTACKS)
def test_dangerous_input_is_rejected_quickly_without_running_code(answer):
    started = time.monotonic()

    result = check(answer, "2")

    assert result.outcome == "wrong"
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(("answer", "reference"), ODD_ROOTS)
def test_odd_root_of_a_negative_number_is_real(answer, reference):
    assert check(answer, reference).outcome == "correct"


def test_heavy_but_true_identity_is_correct_quickly():
    started = time.monotonic()

    result = check("(sin x + cos x)^100 - (1 + sin(2x))^50 + 3", "3")

    assert result.outcome == "correct"
    assert time.monotonic() - started < 2


def test_formula_answer_in_latex_is_checked_the_same_way():
    assert check(r"\frac{6}{2}", "3", form=AnswerForm.FORMULA).outcome == "correct"


def test_verdict_is_about_this_task_and_has_a_score():
    correct = verdict(check("3"))
    wrong = verdict(check("4"))

    assert (correct.task_id, correct.score, correct.max_score) == ("task-1", 1.0, 1.0)
    assert (wrong.task_id, wrong.score, wrong.max_score) == ("task-1", 0.0, 1.0)
    # Проверка без ИИ: вердикт окончательный, преподавателю пересматривать нечего.
    assert not correct.preliminary


def test_neither_the_reference_nor_the_answer_leaks_into_verdict_or_journal():
    reference, answer = "7*z + 12345", "7*z + 54321"

    result = check(answer, reference)

    leaked = str(result.outputs) + str([event.data for event in result.events])
    assert "12345" not in leaked and "54321" not in leaked
    assert [(event.type, event.data) for event in result.events] == [
        ("checked", {"task_id": "task-1", "correct": False, "readable": True})
    ]


@pytest.mark.parametrize("reference", [None, "   "])
def test_task_without_a_reference_fails_the_block(reference):
    with pytest.raises(ValueError, match="нет эталонного ответа"):
        check("3", reference)


def test_unreadable_reference_fails_the_block_without_quoting_it():
    with pytest.raises(ValueError, match="не удалось разобрать") as error:
        check("3", "секрет+")

    assert "секрет" not in str(error.value)


def test_example_manifest_is_a_copy_of_the_block_manifest():
    assert load_manifest(EXAMPLE) == MANIFEST
