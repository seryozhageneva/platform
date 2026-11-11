"""Блок «Получатель: файл» собирает PDF, DOCX или файл импорта вопросов Moodle (ADR 0027).

Готовый файл сохраняется в файлы преподавателя через хранилище платформы, а ссылка на него
публикуется в кабинет преподавателя: оттуда файл скачивают. Что блоку можно сохранять, он
решает сам (ADR 0026): только три своих формата и не больше 10 МиБ.
"""

import hashlib
import json
import re
from typing import Any

from backend.core.contracts.ports import FileKind
from backend.core.contracts.run import BlockEvent, Done, RunContext
from blocks.sink.file.render import Item, as_items, docx_bytes, moodle_xml_bytes, pdf_bytes

MAX_FILE_SIZE = 10 * 1024 * 1024
FORMATS = {
    "pdf": (".pdf", "application/pdf", FileKind.DOCUMENT),
    "docx": (
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        FileKind.DOCUMENT,
    ),
    "moodle_xml": (".xml", "application/xml", FileKind.OTHER),
}
# В имени файла остаются буквы, цифры, пробел, точка, дефис и подчёркивание.
UNSAFE_NAME = re.compile(r"[^\w .-]+")


def _file_name(config: dict[str, Any], extension: str) -> str:
    name = " ".join(UNSAFE_NAME.sub(" ", str(config.get("name") or "")).split()).strip(" .")[:100]
    return f"{name or 'Материалы'}{extension}"


def _content(fmt: str, items: list[Item], name: str, answers: bool) -> bytes:
    if fmt == "pdf":
        return pdf_bytes(items, name, answers=answers)
    if fmt == "docx":
        return docx_bytes(items, name, answers=answers)
    return moodle_xml_bytes(items, answers=answers)


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    fmt = config.get("format", "pdf")
    if fmt not in FORMATS:
        raise ValueError(f"неизвестный формат файла: {fmt}")
    extension, media_type, kind = FORMATS[fmt]
    answers = bool(config.get("answers", True))
    name = _file_name(config, extension)
    items = as_items(inputs["content"])
    content = _content(fmt, items, name.removesuffix(extension), answers)
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("файл получился больше 10 МиБ: выгрузите материалы частями")

    key = hashlib.sha256(
        json.dumps(
            [fmt, name, answers, inputs["content"]], ensure_ascii=False, sort_keys=True
        ).encode()
    ).hexdigest()
    file = await store.save_file(
        key=key, name=name, kind=kind, media_type=media_type, content=content
    )
    data = file.model_dump(mode="json")
    result_id = await store.publish_result(key=key, title=f"Файл «{name}»", content={"file": data})
    return Done(
        outputs={"file": data},
        events=[
            BlockEvent(
                type="file_saved",
                data={"file_id": file.id, "result_id": result_id, "size": len(content)},
            )
        ],
    )
