"""От загрузки документа до сохранённого выхода двух встроенных блоков."""

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.ports import Text
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.triggers.assembly import Assembly
from backend.triggers.worker import run_manual

API = "/api/v1"

PIPELINE = {
    "format": 1,
    "id": "document_to_text",
    "name": "Извлечение текста лекции",
    "params": [{"name": "lecture_file", "title": "Номер файла", "type": "string"}],
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "source",
            "type": "block",
            "block": "source.file",
            "config": {"file_id": {"$param": "lecture_file"}},
        },
        {
            "id": "extract",
            "type": "block",
            "block": "transform.document_to_text",
            "inputs": {"file": "source.file"},
        },
    ],
    "transitions": [
        {"from": "start", "to": "source"},
        {"from": "source", "when": "ok", "to": "extract"},
    ],
}


@pytest.mark.parametrize(
    ("name", "media_type", "sample", "expected"),
    [
        ("lecture.pdf", "application/pdf", "sample_pdf", "First page\n\nSecond page"),
        (
            "lecture.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "sample_docx",
            "Начало лекции\nТема\tДроби\nКонец лекции",
        ),
    ],
)
def test_uploaded_document_becomes_saved_text(
    sessions, teacher, request, name, media_type, sample, expected
):
    jobs = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    registry = load_registry(BUILTIN_BLOCKS)
    assert registry.problems == []
    assembly = Assembly(sessions, registry, FakeLLM())
    app = create_app(assembly, enqueue=enqueue)
    client = TestClient(app, headers={"Origin": "http://testserver"})
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client.cookies.set(SESSION_COOKIE, session)

    uploaded = client.post(
        f"{API}/files",
        params={"name": name},
        headers={"Content-Type": media_type},
        content=request.getfixturevalue(sample),
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    saved = client.post(f"{API}/pipelines", json=PIPELINE)
    assert saved.status_code == 201, saved.text
    pipeline_id = saved.json()["id"]
    launched = client.post(
        f"{API}/pipelines/{pipeline_id}/runs", json={"params": {"lecture_file": file_id}}
    )
    assert launched.status_code == 201, launched.text
    run_id = launched.json()["id"]
    assert jobs == [UUID(run_id)]

    asyncio.run(run_manual(assembly, jobs[0]))
    state = asyncio.run(assembly.runs.load(run_id))
    assert state is not None and state.status == "done", state
    output = Text.model_validate(state.ports["extract"]["text"])
    assert output.text == expected
    assert output.source is not None and output.source.id == file_id
