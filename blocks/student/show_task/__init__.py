"""Блок «Показать задачу и принять ответ»: ждёт ученика на экране «форма ответа» (ADR 0016).

Первый вызов строит экран из задачи: условие, разрешённые формы ответа и подсказку, если она
к этой же задаче. Ответ и эталонное решение в экран не попадают — экран уходит в браузер.

Второй вызов разбирает ответ ученика. Просьба подсказки — исход `hint_requested`, ответ-фото —
`photo` (его ещё нужно распознать), остальное — `answer`. Ответ, который принять нельзя, блок
не принимает и показывает тот же экран снова — это переспрос; причина пишется в журнал.
Текст ответа в журнал не пишется: данные ученика лежат только в выходе блока (ADR 0010).
"""

from typing import Any

from backend.core.contracts.ports import AnswerForm, Hint, Task
from backend.core.contracts.run import BlockEvent, Done, RunContext, Waiting
from backend.core.contracts.screens import AnswerFormData, AnswerFormResponse, ScreenType

DEFAULT_FORMS = [AnswerForm.TEXT, AnswerForm.FORMULA]


async def run(
    inputs: dict[str, Any], config: dict[str, Any], context: RunContext
) -> Done | Waiting:
    if context.human_response is None or context.shown is None:
        return _show(inputs, config)
    shown = AnswerFormData.model_validate(context.shown)
    response = AnswerFormResponse.model_validate(context.human_response)
    reason = _refusal(shown, response)
    if reason is not None:
        refused = BlockEvent(
            type="response_refused", data={"task_id": shown.task_id, "reason": reason}
        )
        return Waiting(screen=ScreenType.ANSWER_FORM, data=context.shown, events=[refused])
    if response.action == "hint":
        asked = BlockEvent(type="hint_requested", data={"task_id": shown.task_id})
        return Done(outcome="hint_requested", events=[asked])
    answer = response.answer
    assert answer is not None  # действие «answer» без ответа контракт не пропускает
    received = BlockEvent(
        type="answer_received", data={"task_id": answer.task_id, "form": answer.form.value}
    )
    return Done(
        outputs={"answer": answer.model_dump(mode="json")},
        outcome="photo" if answer.form is AnswerForm.PHOTO else "answer",
        events=[received],
    )


def _show(inputs: dict[str, Any], config: dict[str, Any]) -> Waiting:
    task = Task.model_validate(inputs["task"])
    hint = Hint.model_validate(inputs["hint"]) if inputs.get("hint") is not None else None
    # Подсказка к прошлой задаче остаётся в состоянии запуска и после смены задачи:
    # показывать её к новой задаче нельзя.
    if hint is not None and hint.task_id != task.id:
        hint = None
    data = AnswerFormData(
        task_id=task.id,
        statement=task.statement,
        forms=config.get("forms") or DEFAULT_FORMS,
        hint=hint,
        can_ask_hint=config.get("allow_hints", True),
    )
    shown = BlockEvent(
        type="task_shown",
        data={"task_id": task.id, "hint_level": hint.level if hint is not None else None},
    )
    return Waiting(screen=ScreenType.ANSWER_FORM, data=data.model_dump(mode="json"), events=[shown])


def _refusal(shown: AnswerFormData, response: AnswerFormResponse) -> str | None:
    """Почему ответ принять нельзя; `None` — можно."""
    if response.action == "hint":
        return None if shown.can_ask_hint else "hints_off"
    answer = response.answer
    assert answer is not None
    # Ответ из старой вкладки на прошлую задачу: засчитать его к этой нельзя.
    if answer.task_id != shown.task_id:
        return "other_task"
    if answer.form not in shown.forms:
        return "form_not_allowed"
    if answer.form is not AnswerForm.PHOTO and not (answer.text or "").strip():
        return "empty_answer"
    # Нулевой символ база не записывает (ADR 0007): такой ответ сломал бы запуск.
    if "\x00" in (answer.text or ""):
        return "bad_characters"
    return None
