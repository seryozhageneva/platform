"""Извлечение кода из сданного файла: поддельное хранилище, без базы."""

import asyncio
from pathlib import Path

import pytest

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import Answer, AnswerForm, FileKind, FileRef
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeStore
from blocks.transform.extract_code import MAX_BYTES, run

ROOT = Path(__file__).resolve().parents[1]
TASK = {
    "id": "double",
    "subject": "информатика",
    "topic": "функции",
    "difficulty": 1,
    "statement": "Напишите программу.",
    "check_method": "code",
    "tests": '[{"stdin": "1\\n", "stdout": "5\\n"}]',
}


def extract(content: bytes | None, *, kind=FileKind.CODE, size=None):
    file = FileRef(
        id="work-3", name="solution.py", kind=kind, media_type="text/x-python", size=size
    )
    store = FakeStore(files=[] if content is None else [(file, content)])
    context = RunContext(run_id="run", node_id="code", pipeline_id="grading", store=store)
    return asyncio.run(run({"file": file.model_dump(), "task": TASK}, {}, context))


def test_code_becomes_answer_to_the_task():
    result = extract("﻿print(2 * int(input()) + 3)\n".encode())
    assert result.outcome == "ok"
    answer = Answer.model_validate(result.outputs["answer"])
    assert (answer.task_id, answer.form) == ("double", AnswerForm.CODE)
    # Метка порядка байтов в начале файла в программу не попадает.
    assert answer.text == "print(2 * int(input()) + 3)\n"


@pytest.mark.parametrize(
    ("content", "options", "message"),
    [
        (b"text", {"kind": FileKind.DOCUMENT}, "не похож на программу"),
        (None, {}, "не найден"),
        (b"  \n", {}, "пустой"),
        (b"\xff\xfe\x00", {}, "UTF-8"),
        (b"print(1)\x00", {}, "UTF-8"),
        (b"x" * (MAX_BYTES + 1), {}, "слишком большой"),
        (b"print(1)", {"size": MAX_BYTES + 1}, "слишком большой"),
    ],
)
def test_unreadable_code_is_an_outcome_not_an_error(content, options, message):
    result = extract(content, **options)
    assert result.outcome == "unreadable"
    assert result.outputs == {}
    [event] = result.events
    assert event.type == "code_unreadable"
    assert message in event.data["message"]


def test_manifest_matches_its_example():
    assert load_manifest(ROOT / "blocks/transform/extract_code/block.yaml") == load_manifest(
        ROOT / "docs/examples/manifests/transform.extract_code.yaml"
    )
