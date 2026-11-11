"""Извлекает текст из документов, загруженных на платформу."""

import asyncio
from io import BytesIO
from typing import Any
from zipfile import BadZipFile
from zlib import error as ZlibError

from docx import Document
from docx.opc.exceptions import OpcError
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from backend.core.contracts.ports import FileRef, Text
from backend.core.contracts.run import BlockEvent, Done, RunContext

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class UnreadableDocument(ValueError):
    """Причина, которую можно показать в журнале без содержимого документа."""


def _pdf_text(stream: BytesIO) -> str:
    reader = PdfReader(stream)
    if reader.is_encrypted:
        raise UnreadableDocument("PDF защищён паролем")
    return "\n\n".join(page.extract_text().strip() for page in reader.pages)


def _docx_text(stream: BytesIO) -> str:
    lines = []
    for element in Document(stream).iter_inner_content():
        if isinstance(element, Paragraph):
            lines.append(element.text)
        else:
            lines.extend("\t".join(cell.text for cell in row.cells) for row in element.rows)
    return "\n".join(lines)


def _extract(content: bytes, media_type: str) -> str:
    try:
        stream = BytesIO(content)
        text = _pdf_text(stream) if media_type == PDF else _docx_text(stream)
    except UnreadableDocument:
        raise
    except (
        PyPdfError,
        BadZipFile,
        OpcError,
        ZlibError,
        SyntaxError,
        KeyError,
        ValueError,
    ) as error:
        raise UnreadableDocument("документ повреждён или не соответствует формату") from error
    if not text.strip():
        raise UnreadableDocument("в документе нет текста")
    return text.strip()


def _unreadable(message: str) -> Done:
    return Done(
        outcome="unreadable",
        events=[BlockEvent(type="document_unreadable", data={"message": message})],
    )


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    file = FileRef.model_validate(inputs["file"])
    if file.media_type not in {PDF, DOCX}:
        return _unreadable("поддерживаются документы PDF и DOCX")
    content = await store.read_file(file.id)
    if content is None:
        return _unreadable("файл не найден")
    try:
        text = await asyncio.to_thread(_extract, content, file.media_type)
    except UnreadableDocument as error:
        return _unreadable(str(error))
    return Done(outputs={"text": Text(text=text, source=file).model_dump(mode="json")})
