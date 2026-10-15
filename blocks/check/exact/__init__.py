"""Блок «Проверка: по эталону»: сравнивает ответ с эталоном как выражения SymPy (ADR 0017).

Эталон — поле `answer` задачи. Ответ, который не удалось разобрать, — вердикт «неверно»:
это ошибка записи ученика, и урок должен идти дальше. Задача без эталона или с эталоном,
который не разбирается, — падение блока: это ошибка преподавателя, её нужно увидеть в журнале.

В вердикте и журнале нет ни эталона, ни ответа: вердикт потом читает тьютор, а журнал
не хранит данные ученика (ADR 0010).
"""

from typing import Any

from sympy import Expr

from backend.core.contracts.ports import Answer, Task, Verdict
from backend.core.contracts.run import BlockEvent, Done, RunContext
from blocks.check.exact.math_compare import Unreadable, read, same

CORRECT = "Ответ совпадает с эталоном."
WRONG = "Ответ не совпадает с эталоном."
UNREADABLE = "Не удалось разобрать ответ: проверьте запись."


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    task = Task.model_validate(inputs["task"])
    answer = Answer.model_validate(inputs["answer"])
    reference = _reference(task)
    readable = True
    try:
        correct = same(read(answer.text), reference)
    except Unreadable:
        readable, correct = False, False
    verdict = Verdict(
        correct=correct,
        task_id=task.id,
        score=1.0 if correct else 0.0,
        max_score=1.0,
        comment=CORRECT if correct else WRONG if readable else UNREADABLE,
    )
    checked = BlockEvent(
        type="checked", data={"task_id": task.id, "correct": correct, "readable": readable}
    )
    return Done(
        outputs={"verdict": verdict.model_dump(mode="json")},
        outcome="correct" if correct else "wrong",
        events=[checked],
    )


def _reference(task: Task) -> list[Expr]:
    if task.answer is None or not task.answer.strip():
        raise ValueError(f"у задачи {task.id} нет эталонного ответа")
    try:
        return read(task.answer)
    except Unreadable as error:
        raise ValueError(
            f"эталонный ответ задачи {task.id} не удалось разобрать: {error}"
        ) from None
