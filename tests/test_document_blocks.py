"""Чтение документов из поддельного хранилища без базы."""

import asyncio
from pathlib import Path

import pytest

from backend.core.contracts.manifest import load_manifest
from backend.core.contracts.ports import FileKind, FileRef, Text
from backend.core.contracts.run import RunContext
from backend.core.contracts.testing import FakeStore
from blocks.source.file import run as take_file
from blocks.transform.document_to_text import DOCX, PDF, run


def context(store: FakeStore) -> RunContext:
    return RunContext(run_id="run", node_id="document", pipeline_id="documents", store=store)


def file_ref(media_type: str) -> FileRef:
    return FileRef(
        id="example", name="Лекция", kind=FileKind.DOCUMENT, media_type=media_type, student_id="owl"
    )


@pytest.mark.parametrize("found", [True, False])
def test_source_takes_only_file_description(found):
    class DescriptionStore(FakeStore):
        async def read_file(self, file_id: str) -> bytes | None:
            pytest.fail("источнику достаточно описания файла")

    file = file_ref(PDF)
    store = DescriptionStore(files=[(file, b"example")] if found else [])
    result = asyncio.run(take_file({}, {"file_id": file.id}, context(store)))
    if found:
        assert result.outcome == "ok"
        assert FileRef.model_validate(result.outputs["file"]) == file
    else:
        assert result.outcome == "missing"
        assert result.outputs == {}
        assert result.events[0].type == "file_missing"


@pytest.mark.parametrize(
    ("media_type", "sample", "expected"),
    [
        (PDF, "sample_pdf", "First page\n\nSecond page"),
        (DOCX, "sample_docx", "Начало лекции\nТема\tДроби\nКонец лекции"),
    ],
)
def test_extracts_text_in_document_order_and_keeps_the_source(
    media_type, sample, expected, request
):
    file = file_ref(media_type)
    store = FakeStore(files=[(file, request.getfixturevalue(sample))])
    result = asyncio.run(run({"file": file.model_dump()}, {}, context(store)))
    assert result.outcome == "ok"
    assert Text.model_validate(result.outputs["text"]) == Text(text=expected, source=file)


@pytest.mark.parametrize(
    ("media_type", "example", "reason"),
    [
        (PDF, "broken", "документ повреждён"),
        (DOCX, "broken", "документ повреждён"),
        (PDF, "empty", "в документе нет текста"),
        (PDF, "encrypted", "PDF защищён паролем"),
        (PDF, "missing", "файл не найден"),
        ("image/png", "broken", "поддерживаются документы PDF и DOCX"),
    ],
)
def test_unreadable_document_records_a_reason(media_type, example, reason, make_pdf):
    file = file_ref(media_type)
    if example == "empty":
        content = make_pdf("")
    elif example == "encrypted":
        content = make_pdf("Lecture", password="fixture")
    else:
        content = b"damaged file"
    store = FakeStore(files=[] if example == "missing" else [(file, content)])
    result = asyncio.run(run({"file": file.model_dump()}, {}, context(store)))
    assert result.outcome == "unreadable"
    assert result.outputs == {}
    assert result.events[0].type == "document_unreadable"
    assert reason in result.events[0].data["message"]


@pytest.mark.parametrize("block", ["source.file", "transform.document_to_text"])
def test_document_manifest_matches_its_example(block):
    root = Path(__file__).resolve().parents[1]
    builtin = root / "blocks" / Path(*block.split(".")) / "block.yaml"
    example = root / "docs" / "examples" / "manifests" / f"{block}.yaml"
    assert load_manifest(builtin) == load_manifest(example)
