"""Достаёт текст программы из сданного файла с кодом."""

from typing import Any

from backend.core.contracts.ports import Answer, AnswerForm, FileKind, FileRef, Task
from backend.core.contracts.run import BlockEvent, Done, RunContext

# Больше, чем принимает песочница: слишком большую программу она отклонит сама
# с понятным комментарием, а здесь отсекается только явно не код.
MAX_BYTES = 1024 * 1024


def _unreadable(message: str) -> Done:
    return Done(
        outcome="unreadable",
        events=[BlockEvent(type="code_unreadable", data={"message": message})],
    )


def _decode(content: bytes) -> str | None:
    try:
        # utf-8-sig убирает метку порядка байтов, которую добавляют некоторые редакторы.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    file = FileRef.model_validate(inputs["file"])
    task = Task.model_validate(inputs["task"])
    if file.kind is not FileKind.CODE:
        return _unreadable("файл не похож на программу")
    if file.size is not None and file.size > MAX_BYTES:
        return _unreadable("файл слишком большой для программы")
    content = await store.read_file(file.id)
    if content is None:
        return _unreadable("файл не найден")
    if len(content) > MAX_BYTES:
        return _unreadable("файл слишком большой для программы")
    code = _decode(content)
    if code is None:
        return _unreadable("программа должна быть текстом в кодировке UTF-8")
    if not code.strip():
        return _unreadable("файл пустой")
    answer = Answer(task_id=task.id, form=AnswerForm.CODE, text=code)
    return Done(outputs={"answer": answer.model_dump(mode="json")})
