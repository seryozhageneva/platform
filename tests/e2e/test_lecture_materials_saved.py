"""Сценарий 3 целиком: от лекции до банка задач, конспекта в кабинете и файла для Moodle.

Критерий задачи 22: результаты сохраняются (банк, кабинет, файлы) и выгружаются
(скачивание файла). Модель фейковая, подтверждает задачи преподаватель через API.
Задача 24: узел «Решить независимо» не видит эталон и решение задачи.
"""

import asyncio
import json
import xml.etree.ElementTree as ET
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
API = "/api/v1"
SUMMARY = {"summary": "Тема лекции — дроби.", "key_concepts": ["дробь", "числитель"]}
TASKS = [
    {
        "id": f"task-{number}",
        "subject": "математика",
        "topic": "дроби",
        "difficulty": 1,
        "statement": statement,
        "check_method": "short_answer",
        "answer": answer,
        "solution": "Числитель записывают над чертой.",
    }
    for number, statement, answer in ((1, "Числитель дроби 3/4?", "3"), (2, "Числитель 5/7?", "5"))
]


def test_approved_lecture_materials_are_saved_and_downloaded(sessions, teacher, sample_docx):
    solved = [{"task_id": task["id"], "form": "text", "text": task["answer"]} for task in TASKS]
    llm = FakeLLM([SUMMARY, TASKS, *solved])
    jobs: list[UUID] = []

    async def enqueue(run_id: UUID) -> None:
        jobs.append(run_id)

    registry = load_registry(BUILTIN_BLOCKS)
    assert registry.problems == []
    assembly = Assembly(sessions, registry, llm)
    session, _ = asyncio.run(AuthRepository(sessions).start_teacher(teacher.id))
    client = TestClient(
        create_app(assembly, enqueue=enqueue), headers={"Origin": "http://testserver"}
    )
    client.cookies.set(SESSION_COOKIE, session)

    uploaded = client.post(
        f"{API}/files",
        params={"name": "lecture.docx"},
        headers={"Content-Type": DOCX},
        content=sample_docx,
    )
    assert uploaded.status_code == 201, uploaded.text
    pipeline = json.loads(SCENARIO.read_text(encoding="utf-8"))
    saved = client.post(f"{API}/pipelines", json=pipeline)
    assert saved.status_code == 201, saved.text
    launched = client.post(
        f"{API}/pipelines/{saved.json()['id']}/runs",
        json={"params": {"lecture_file": uploaded.json()["id"]}},
    )
    assert launched.status_code == 201, launched.text
    run_id = launched.json()["id"]
    asyncio.run(run_manual(assembly, jobs[0]))

    # «Решить независимо» видит номер и условие задачи, но не эталон и не решение (ADR 0029).
    solving = [call.messages[0].content for call in llm.calls[2:]]
    assert len(solving) == len(TASKS)
    for prompt, task in zip(solving, TASKS, strict=True):
        assert task["id"] in prompt and task["statement"] in prompt
        assert task["solution"] not in prompt
        assert '"answer"' not in prompt

    run = client.get(f"{API}/runs/{run_id}").json()
    assert run["status"] == "waiting", run
    [waiting] = run["waiting"]
    decision = {
        "node_id": waiting["node_id"],
        "approval_id": waiting["approval_id"],
        "response": {
            "rows": [{"index": 0, "values": {"/task/statement": "Исправлено"}}, {"index": 1}]
        },
    }
    finished = client.post(f"{API}/runs/{run_id}/responses", json=decision)
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "done", finished.json()

    bank = client.get(f"{API}/tasks", params={"status": "approved"}).json()
    assert sorted(task["statement"] for task in bank) == ["Исправлено", "Числитель 5/7?"]

    results = client.get(f"{API}/results").json()
    by_title = {result["title"]: result for result in results}
    assert by_title["Конспект лекции"]["content"] == SUMMARY
    assert by_title["Конспект лекции"]["student_id"] is None
    [file_result] = [result for result in results if result["title"].startswith("Файл")]
    file = file_result["content"]["file"]
    assert (file["name"], file["media_type"]) == ("Материалы.xml", "application/xml")

    downloaded = client.get(f"{API}/files/{file['id']}/content")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    quiz = ET.fromstring(downloaded.content)
    questions = quiz.findall("question")
    assert [question.get("type") for question in questions] == ["shortanswer", "shortanswer"]
    assert "Исправлено" in questions[0].findtext("questiontext/text")
    assert [question.findtext("answer/text") for question in questions] == ["3", "5"]
