"""Блоки-получатели «Кабинет», «Банк задач» и «Файл» на поддельном хранилище (ADR 0027)."""

import asyncio
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeStore
from blocks.sink.cabinet import run as to_cabinet
from blocks.sink.file import run as to_file
from blocks.sink.task_bank import run as to_bank

ROOT = Path(__file__).resolve().parents[1]
TASK = {
    "id": "draft-1",
    "subject": "математика",
    "topic": "Дроби",
    "difficulty": 1,
    "statement": "Сложите 1/2 и 1/3. Знаки <b> & </b> — просто текст.",
    "check_method": "short_answer",
    "answer": "5/6",
    "solution": "Общий знаменатель — 6.",
}
ESSAY = {
    **TASK,
    "id": "draft-2",
    "statement": "Объясните, почему 1/2 = 2/4.",
    "check_method": "long_answer",
    "answer": None,
    "rubric": "Названо основное свойство дроби.",
}


def context(store: FakeStore, student_id: str | None = None) -> RunContext:
    return RunContext(
        run_id="run", node_id="sink", pipeline_id="p", student_id=student_id, store=store
    )


def call(block, inputs, config, store, student_id=None):
    return asyncio.run(block(inputs, config, context(store, student_id)))


@pytest.mark.parametrize("name", ["cabinet", "task_bank", "file"])
def test_manifest_matches_its_example(name):
    assert load_manifest(ROOT / f"blocks/sink/{name}/block.yaml") == load_manifest(
        ROOT / f"docs/examples/manifests/sink.{name}.yaml"
    )


# Кабинет


def test_cabinet_publishes_to_teacher_by_default_and_once_on_repeat():
    store = FakeStore()
    content = {"summary": "Дроби", "key_concepts": ["дробь"]}
    first = call(to_cabinet, {"content": content}, {"title": "Конспект"}, store)
    again = call(to_cabinet, {"content": content}, {"title": "Конспект"}, store)

    [result] = store.published
    assert (result.title, result.content, result.student_id) == ("Конспект", content, None)
    assert first.events == again.events
    assert first.events[0].data == {"result_id": result.id, "to": "teacher"}


def test_cabinet_sends_to_the_student_of_the_run():
    store = FakeStore(students=["owl"])
    call(to_cabinet, {"content": "Итог урока"}, {"to": "student"}, store, student_id="owl")
    [result] = store.published
    assert (result.student_id, result.title) == ("owl", "Результат")


def test_cabinet_without_student_of_the_run_refuses():
    with pytest.raises(ValueError, match="нет ученика"):
        call(to_cabinet, {"content": "Итог"}, {"to": "student"}, FakeStore())


def test_cabinet_takes_recipient_from_the_value_and_keeps_students_apart():
    store = FakeStore(students=["owl", "fox"])
    config = {"to": "recipient", "title": "Рекомендации"}
    for student in ("owl", "fox"):
        call(
            to_cabinet,
            {"content": "Повторить дроби", "recipient": {"student_id": student}},
            config,
            store,
        )
    assert [result.student_id for result in store.published] == ["owl", "fox"]


@pytest.mark.parametrize("recipient", [None, {"student_id": ""}, {"name": "owl"}, "owl"])
def test_cabinet_without_recipient_in_the_value_refuses(recipient):
    inputs = {"content": "Итог"} | ({} if recipient is None else {"recipient": recipient})
    with pytest.raises(ValueError, match="не указан ученик"):
        call(to_cabinet, inputs, {"to": "recipient"}, FakeStore())


def test_cabinet_refuses_a_stranger():
    inputs = {"content": "Итог", "recipient": {"student_id": "stranger"}}
    with pytest.raises(ValueError, match="ученик не найден"):
        call(to_cabinet, inputs, {"to": "recipient"}, FakeStore(students=["owl"]))


# Банк задач


def test_bank_saves_each_task_once():
    store = FakeStore()
    first = call(to_bank, {"task": TASK}, {}, store)
    again = call(to_bank, {"task": TASK}, {}, store)
    other = call(to_bank, {"task": ESSAY}, {}, store)

    assert [task.statement for task in store.tasks] == [TASK["statement"], ESSAY["statement"]]
    assert first.outputs == again.outputs
    assert first.outputs["task"]["id"] == store.tasks[0].id != TASK["id"]
    assert other.events[0].data == {"task_id": store.tasks[1].id}


# Файл


def saved_file(result, store):
    ref, content = store.files[result.outputs["file"]["id"]]
    return ref, content


def test_pdf_has_cyrillic_tasks_and_answers():
    store = FakeStore()
    result = call(to_file, {"content": [TASK, ESSAY]}, {"format": "pdf", "name": "Дроби"}, store)
    ref, content = saved_file(result, store)
    assert (ref.name, ref.media_type, ref.size) == ("Дроби.pdf", "application/pdf", len(content))
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    for expected in ("Задача 1", "Сложите 1/2 и 1/3", "5/6", "Задача 2", "основное свойство"):
        assert expected in text


def test_docx_without_answers_keeps_only_statements():
    store = FakeStore()
    config = {"format": "docx", "answers": False}
    result = call(to_file, {"content": [TASK]}, config, store)
    ref, content = saved_file(result, store)
    assert ref.name == "Материалы.docx"
    text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    assert "Сложите 1/2 и 1/3" in text
    assert "5/6" not in text and "Общий знаменатель" not in text


def test_docx_shows_summary_fields_and_drops_service_ones():
    store = FakeStore()
    summary = {"summary": "Дробь — часть целого.", "key_concepts": ["числитель", "знаменатель"]}
    text_value = {"text": "Текст лекции", "source": {"id": "f1"}}
    result = call(to_file, {"content": [summary, text_value]}, {"format": "docx"}, store)
    _, content = saved_file(result, store)
    text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    assert "Конспект\nДробь — часть целого." in text
    assert "Ключевые понятия\n• числитель\n• знаменатель" in text
    assert "Текст лекции" in text and "f1" not in text


def test_moodle_xml_has_short_answer_and_essay():
    store = FakeStore()
    result = call(to_file, {"content": [TASK, ESSAY]}, {"format": "moodle_xml"}, store)
    ref, content = saved_file(result, store)
    assert (ref.name, ref.media_type) == ("Материалы.xml", "application/xml")
    short, essay = ET.fromstring(content).findall("question")
    assert (short.get("type"), essay.get("type")) == ("shortanswer", "essay")
    assert short.find("answer").get("fraction") == "100"
    assert short.findtext("answer/text") == "5/6"
    # Текст задачи экранирован как HTML: теги из условия не становятся разметкой.
    assert "&lt;b&gt; &amp; &lt;/b&gt;" in short.findtext("questiontext/text")
    assert short.find("questiontext").get("format") == "html"
    assert "основное свойство" in essay.findtext("graderinfo/text")


def test_moodle_xml_accepts_only_tasks():
    with pytest.raises(ValueError, match="только из задач"):
        call(to_file, {"content": [TASK, "просто текст"]}, {"format": "moodle_xml"}, FakeStore())


def test_file_is_saved_and_published_once_on_repeat():
    store = FakeStore()
    first = call(to_file, {"content": [TASK]}, {"format": "docx"}, store)
    again = call(to_file, {"content": [TASK]}, {"format": "docx"}, store)
    assert first.outputs == again.outputs
    assert len(store.files) == 1
    [result] = store.published
    assert result.title == "Файл «Материалы.docx»"
    assert result.content == {"file": first.outputs["file"]}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "etc passwd.pdf"),
        ("  ", "Материалы.pdf"),
        ("Урок: 1/2", "Урок 1 2.pdf"),
    ],
)
def test_file_name_is_made_safe(name, expected):
    store = FakeStore()
    result = call(to_file, {"content": [TASK]}, {"name": name}, store)
    assert result.outputs["file"]["name"] == expected


def test_file_control_characters_are_dropped():
    store = FakeStore()
    task = {**TASK, "statement": "Сложите\x00 дроби\x0b"}
    for fmt in ("pdf", "docx", "moodle_xml"):
        call(to_file, {"content": [task]}, {"format": fmt}, store)
    assert len(store.files) == 3


def test_empty_content_refuses():
    with pytest.raises(ValueError, match="нет данных"):
        call(to_file, {"content": []}, {}, FakeStore())


def test_too_big_file_refuses(monkeypatch):
    monkeypatch.setattr("blocks.sink.file.MAX_FILE_SIZE", 100)
    with pytest.raises(ValueError, match="больше 10 МиБ"):
        call(to_file, {"content": [TASK]}, {"format": "moodle_xml"}, FakeStore())


def test_moodle_xml_keeps_asterisk_in_answer_literal():
    store = FakeStore()
    task = {**TASK, "answer": "2*x"}
    result = call(to_file, {"content": [task]}, {"format": "moodle_xml"}, store)
    _, content = saved_file(result, store)
    [question] = ET.fromstring(content).findall("question")
    assert question.findtext("answer/text") == "2\\*x"
