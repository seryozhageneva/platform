"""Сборка файлов блока «Получатель: файл»: PDF, DOCX и Moodle XML.

На вход приходит список значений. Задача (`Task`) выводится как задача: условие, а по
настройке — ответ и решение. Любое другое значение выводится как текст или как пары
«поле — значение»: так выгружаются конспект и другие результаты ИИ-обработки.
"""

import json
import re
import xml.etree.ElementTree as ET
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import ValidationError

from backend.core.contracts.ports import CheckMethod, Task

FONTS = Path(__file__).parent / "fonts"
# Символы, которые нельзя записать ни в XML, ни в DOCX (он тоже XML внутри).
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
LABELS = {"summary": "Конспект", "key_concepts": "Ключевые понятия", "text": None}
# Служебные поля, которые преподавателю в файле не нужны: ссылка на исходный файл и номера.
SKIPPED = {"source", "student_id", "meta", "id"}
METHODS = {
    CheckMethod.SHORT_ANSWER: "краткий ответ",
    CheckMethod.LONG_ANSWER: "развёрнутое решение",
    CheckMethod.CODE: "код",
}

# Абзац: подпись (может не быть) и текст.
Paragraph = tuple[str | None, str]
Item = Task | list[Paragraph]


def clean(text: str) -> str:
    return CONTROL.sub("", text)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return "\n".join(f"• {part}" for part in value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def _paragraphs(value: Any) -> list[Paragraph]:
    if isinstance(value, dict):
        return [
            (LABELS.get(name, name), _as_text(part))
            for name, part in value.items()
            if name not in SKIPPED and part not in (None, "", [])
        ]
    return [(None, _as_text(value))]


def as_items(content: Any) -> list[Item]:
    """Значения со входа — в задачи и абзацы. Пустой вход — ошибка: выгружать нечего."""
    values = content if isinstance(content, list) else [content]
    items: list[Item] = []
    for value in values:
        try:
            items.append(Task.model_validate(value))
        except ValidationError:
            paragraphs = _paragraphs(value)
            if paragraphs:
                items.append(paragraphs)
    if not items:
        raise ValueError("на входе нет данных для файла")
    return items


def _task_paragraphs(task: Task, *, answers: bool) -> list[Paragraph]:
    paragraphs: list[Paragraph] = [
        (None, f"{task.subject} · {task.topic} · сложность {task.difficulty}"),
        ("Условие", task.statement),
    ]
    if answers:
        for label, text in (
            ("Ответ", task.answer),
            ("Решение", task.solution),
            ("Критерии оценки", task.rubric),
            ("Тесты", task.tests),
        ):
            if text:
                paragraphs.append((label, text))
    return paragraphs


def _sections(items: list[Item], *, answers: bool) -> list[tuple[str | None, list[Paragraph]]]:
    """Разделы файла: у задачи заголовок «Задача N», у остального — без заголовка."""
    sections: list[tuple[str | None, list[Paragraph]]] = []
    number = 0
    for item in items:
        if isinstance(item, Task):
            number += 1
            sections.append((f"Задача {number}", _task_paragraphs(item, answers=answers)))
        else:
            sections.append((None, item))
    return sections


def pdf_bytes(items: list[Item], title: str, *, answers: bool) -> bytes:
    pdf = FPDF()
    pdf.add_font("DejaVu", "", FONTS / "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", FONTS / "DejaVuSans-Bold.ttf")
    pdf.set_title(clean(title))
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 9, clean(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for heading, paragraphs in _sections(items, answers=answers):
        pdf.ln(4)
        if heading:
            pdf.set_font("DejaVu", "B", 13)
            pdf.multi_cell(0, 7, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for label, text in paragraphs:
            if label:
                pdf.set_font("DejaVu", "B", 11)
                pdf.multi_cell(0, 6, clean(label), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("DejaVu", "", 11)
            pdf.multi_cell(0, 6, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
    return bytes(pdf.output())


def docx_bytes(items: list[Item], title: str, *, answers: bool) -> bytes:
    document = Document()
    document.core_properties.title = clean(title)
    document.add_heading(clean(title), level=0)
    for heading, paragraphs in _sections(items, answers=answers):
        if heading:
            document.add_heading(heading, level=1)
        for label, text in paragraphs:
            if label:
                document.add_paragraph().add_run(clean(label)).bold = True
            document.add_paragraph(clean(text))
    content = BytesIO()
    document.save(content)
    return content.getvalue()


def _text(parent: ET.Element, tag: str, text: str, **attributes: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes)
    ET.SubElement(element, "text").text = text
    return element


def _html(text: str) -> str:
    """Текст для поля Moodle в формате HTML: спецсимволы экранированы, переносы сохранены."""
    return "<p>" + escape(clean(text)).replace("\n", "<br>") + "</p>"


def moodle_xml_bytes(items: list[Item], *, answers: bool) -> bytes:
    """Файл импорта вопросов Moodle (формат Moodle XML).

    Краткий ответ — вопрос «Короткий ответ» с эталоном, остальное — «Эссе»: его оценивает
    преподаватель. Решение попадает в общий отзыв и в информацию для оценщика.
    """
    tasks = [item for item in items if isinstance(item, Task)]
    if len(tasks) != len(items):
        raise ValueError("файл импорта Moodle собирается только из задач")
    quiz = ET.Element("quiz")
    for number, task in enumerate(tasks, start=1):
        short = task.check_method is CheckMethod.SHORT_ANSWER and bool(task.answer)
        question = ET.SubElement(quiz, "question", type="shortanswer" if short else "essay")
        name = f"{number}. {task.topic} — {METHODS[task.check_method]}"
        _text(question, "name", clean(name)[:250])
        _text(question, "questiontext", _html(task.statement), format="html")
        solution = _html(task.solution) if answers and task.solution else ""
        _text(question, "generalfeedback", solution, format="html")
        ET.SubElement(question, "defaultgrade").text = "1"
        ET.SubElement(question, "penalty").text = "0.3333333"
        ET.SubElement(question, "hidden").text = "0"
        if short:
            ET.SubElement(question, "usecase").text = "0"
            # В «Коротком ответе» звёздочка — «любые символы»; в эталоне она должна значить себя.
            reference = clean(task.answer or "").replace("*", "\\*")
            answer = _text(question, "answer", reference, fraction="100")
            answer.set("format", "moodle_auto_format")
            _text(answer, "feedback", "", format="html")
        else:
            ET.SubElement(question, "responseformat").text = "editor"
            ET.SubElement(question, "responserequired").text = "1"
            ET.SubElement(question, "responsefieldlines").text = "15"
            ET.SubElement(question, "attachments").text = "0"
            info = [text for text in (task.answer, task.solution, task.rubric) if answers and text]
            _text(question, "graderinfo", "".join(_html(text) for text in info), format="html")
            _text(question, "responsetemplate", "", format="html")
    ET.indent(quiz)
    return ET.tostring(quiz, encoding="utf-8", xml_declaration=True)
