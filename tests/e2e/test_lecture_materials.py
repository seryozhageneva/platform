"""Сценарий 3 от загруженной лекции до сохранённых результатов ИИ-обработки."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.deps import SESSION_COOKIE
from backend.core.contracts.testing import FakeLLM
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.models.auth import AuthRepository
from backend.triggers.assembly import Assembly
from backend.triggers.worker import run_manual

SCENARIO = Path(__file__).resolve().parents[2] / "docs/examples/pipelines/scenario-3-materials.json"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_uploaded_lecture_becomes_summary_and_tasks(sessions, teacher, sample_docx):
    pipeline = json.loads(SCENARIO.read_text(encoding="utf-8"))
    generation = {"start", "get_file", "extract", "summarize", "make_tasks"}
    pipeline["nodes"] = [node for node in pipeline["nodes"] if node["id"] in generation]
    pipeline["transitions"] = [
        move
        for move in pipeline["transitions"]
        if move["from"] in generation and move["to"] in generation
    ]
    pipeline["transitions"].append({"from": "summarize", "to": "make_tasks"})
    summary = {"summary": "Тема лекции — дроби.", "key_concepts": ["дробь"]}
    tasks = [
        {
            "id": "task-1",
            "subject": "математика",
            "topic": "дроби",
            "difficulty": 1,
            "statement": "Какой числитель у дроби 3/4?",
            "check_method": "short_answer",
            "answer": "3",
            "solution": "Числитель записывают над чертой.",
        }
    ]
    llm = FakeLLM([summary, tasks])
    jobs = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    registry = load_registry(BUILTIN_BLOCKS)
    assert registry.problems == []
    assembly = Assembly(sessions, registry, llm)
    app = create_app(assembly, enqueue=enqueue)
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        client.cookies.set(SESSION_COOKIE, session)
        uploaded = client.post(
            "/api/v1/files",
            params={"name": "lecture.docx"},
            headers={"Content-Type": DOCX},
            content=sample_docx,
        )
        assert uploaded.status_code == 201, uploaded.text
        saved = client.post("/api/v1/pipelines", json=pipeline)
        assert saved.status_code == 201, saved.text
        pipeline_id = saved.json()["id"]
        launched = client.post(
            f"/api/v1/pipelines/{pipeline_id}/runs",
            json={"params": {"lecture_file": uploaded.json()["id"]}},
        )
        assert launched.status_code == 201, launched.text

    run_id = launched.json()["id"]
    assert jobs == [UUID(run_id)]
    asyncio.run(run_manual(assembly, jobs[0]))
    state = asyncio.run(assembly.runs.load(run_id))
    assert state is not None and state.status == "done", state
    assert state.ports["summarize"]["result"] == summary
    assert state.ports["make_tasks"]["result"] == tasks
    assert len(llm.calls) == 2
    assert "Начало лекции" in llm.calls[0].messages[0].content
    assert summary["summary"] in llm.calls[1].messages[0].content
