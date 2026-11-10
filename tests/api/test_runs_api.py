"""Запуск пайплайна запросом и журнал событий — критерий задачи 08.

Триггер «вручную»: преподаватель присылает запрос, слой сборки соединяет движок с базой,
реестром и моделью, а журнал событий читается следующим запросом.
"""

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta

from api_fakes import THREE_FAKES, chain, launch, launch_and_read, run_queued, saved
from sqlalchemy import func, select, update

from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus, WaitingFor
from backend.models.llm_calls import LLMCallRepository
from backend.models.run_store import PgRunStore
from backend.models.tables import RunRow

API = "/api/v1"


def journal(client, headers, run_id) -> list[tuple[str, str]]:
    response = client.get(f"{API}/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200, response.text
    return [(event["node_id"], event["type"]) for event in response.json()]


def test_pipeline_is_started_by_a_request_and_events_are_in_the_journal(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)

    started = launch(client, me, pipeline_id)

    assert started.status_code == 201, started.text
    queued = started.json()
    assert queued["status"] == "running"
    assert journal(client, me, queued["id"]) == [("start", "run_queued")]
    run_queued(client, queued["id"])
    run = client.get(f"{API}/runs/{queued['id']}", headers=me).json()
    assert run["status"] == "done"
    assert run["pipeline_id"] == pipeline_id
    assert run["pipeline_version"] == 1
    assert run["current"] == [] and run["error"] is None

    # Состояние и журнал читаются отдельными запросами — из базы, а не из памяти сервера.
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    assert [(event["node_id"], event["type"]) for event in events] == [
        ("start", "run_queued"),
        ("start", "run_started"),
        ("make", "text_made"),
        ("make", "node_done"),
        ("upper", "node_done"),
        ("keep", "text_kept"),
        ("keep", "node_done"),
        ("keep", "run_done"),
    ]
    assert events[1]["data"] == {"trigger": "manual"}
    assert events[5]["data"] == {"text": "ПРИВЕТ"}
    assert all(event["created_at"] for event in events)


def test_params_from_the_request_reach_the_blocks(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)

    run = launch_and_read(client, me, pipeline_id, phrase="логарифмы").json()

    assert run["params"] == {"phrase": "логарифмы"}
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    assert {"text": "ЛОГАРИФМЫ"} in [event["data"] for event in events]


def test_launch_without_a_body_uses_default_params(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)

    started = client.post(f"{API}/pipelines/{pipeline_id}/runs", headers=me)

    assert started.status_code == 201, started.text
    assert started.json()["params"] == {"phrase": "привет"}


def test_every_launch_is_a_new_run(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)

    first = launch(client, me, pipeline_id).json()
    second = launch(client, me, pipeline_id).json()

    assert first["id"] != second["id"]


def test_manual_launch_requires_matching_version_if_requested(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)
    renamed = {**THREE_FAKES, "name": "Новая версия"}
    assert client.put(f"{API}/pipelines/{pipeline_id}", headers=me, json=renamed).status_code == 200
    url = f"{API}/pipelines/{pipeline_id}/runs"

    stale = client.post(url, headers=me, json={"expected_version": 1})
    assert stale.status_code == 422
    assert stale.json()["problems"][0]["code"] == "version_changed"
    assert client.get(f"{API}/runs", headers=me).json() == []

    started = client.post(url, headers=me, json={"expected_version": 2})
    assert started.status_code == 201
    assert started.json()["pipeline_version"] == 2


def test_teacher_lists_only_own_runs_with_progress_and_original_version(
    client, me, stranger, sessions, teacher
):
    pipeline_id = saved(client, me, THREE_FAKES)
    finished = launch_and_read(client, me, pipeline_id).json()
    renamed = {**THREE_FAKES, "name": "Переименованный пайплайн"}
    assert client.put(f"{API}/pipelines/{pipeline_id}", headers=me, json=renamed).status_code == 200
    student = client.post(f"{API}/students", headers=me, json={"name": "Сова"}).json()
    foreign_pipeline = saved(client, stranger, THREE_FAKES)
    foreign = launch(client, stranger, foreign_pipeline).json()

    async def add_runs():
        store = PgRunStore(sessions)
        waiting = []
        for who in ("student", "teacher"):
            state = RunState(
                run_id=str(uuid.uuid4()),
                pipeline_id=pipeline_id,
                pipeline_version=2,
                student_id=student["id"] if who == "student" else None,
                teacher_id=str(teacher.id),
                status=RunStatus.WAITING,
                current=["step"],
                waiting=[
                    WaitingFor(
                        node_id="step",
                        who=who,
                        screen=ScreenType.ANSWER_FORM
                        if who == "student"
                        else ScreenType.REVIEW_TABLE,
                        data={"statement": "Только для подробностей"},
                    )
                ],
            )
            await store.save(state)
            waiting.append(uuid.UUID(state.run_id))
        failed = uuid.uuid4()
        await store.save(
            RunState(
                run_id=str(failed),
                pipeline_id=pipeline_id,
                pipeline_version=2,
                teacher_id=str(teacher.id),
                status=RunStatus.ERROR,
                current=["broken"],
                error="Не удалось выполнить шаг",
            )
        )
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            await session.execute(
                update(RunRow).where(RunRow.id.in_(waiting)).values(updated_at=now)
            )
            await session.execute(
                update(RunRow)
                .where(RunRow.id == failed)
                .values(updated_at=now + timedelta(seconds=1))
            )
            await session.execute(
                update(RunRow)
                .where(RunRow.id == uuid.UUID(finished["id"]))
                .values(updated_at=now - timedelta(seconds=1))
            )
        return *waiting, failed

    student_run, approval_run, failed = asyncio.run(add_runs())
    response = client.get(f"{API}/runs", headers=me)
    assert response.status_code == 200, response.text
    runs = response.json()
    assert [run["id"] for run in runs] == [
        str(failed),
        *(str(key) for key in sorted((student_run, approval_run), reverse=True)),
        finished["id"],
    ]
    by_id = {run["id"]: run for run in runs}
    assert runs[0]["status"] == "error"
    assert runs[0]["current"] == ["broken"]
    assert runs[0]["error"] == "Не удалось выполнить шаг"
    assert runs[0]["pipeline_name"] == renamed["name"]
    assert runs[-1]["status"] == "done"
    assert runs[-1]["student_name"] is None
    assert runs[-1]["pipeline_name"] == THREE_FAKES["name"]
    assert runs[-1]["pipeline_version"] == 1
    assert by_id[str(student_run)]["student_name"] == "Сова"
    assert by_id[str(student_run)]["waiting"] == [{"node_id": "step", "who": "student"}]
    assert by_id[str(approval_run)]["waiting"] == [{"node_id": "step", "who": "teacher"}]
    assert {run["id"] for run in client.get(f"{API}/runs", headers=stranger).json()} == {
        foreign["id"]
    }
    assert client.get(f"{API}/runs/{foreign['id']}/events", headers=me).status_code == 404
    assert client.get(f"{API}/runs").status_code == 401


def test_pipeline_without_manual_launch_is_not_started(client, me):
    pipeline_id = saved(client, me, chain(("keep", "sink.fake_keep"), launches=("student",)))

    refused = launch(client, me, pipeline_id)

    assert refused.status_code == 422
    assert refused.json()["problems"] == [
        {
            "node": "start",
            "code": "launch_not_allowed",
            "message": "у пайплайна нет способа запуска «manual»; есть только: student",
        }
    ]


def test_bad_params_are_refused_with_a_clear_reason(client, me):
    pipeline = copy.deepcopy(THREE_FAKES)
    pipeline["params"] += [
        {"name": "count", "title": "Число задач", "type": "integer", "default": 3},
        {"name": "topic", "title": "Тема", "type": "string"},
    ]
    pipeline_id = saved(client, me, pipeline)

    refused = launch(client, me, pipeline_id, count="три", extra=1)

    assert refused.status_code == 422
    assert refused.json()["message"] == "пайплайн нельзя запустить"
    assert [problem["message"] for problem in refused.json()["problems"]] == [
        "у пайплайна нет параметра «extra»",
        "параметр «count» (Число задач): ожидается целое число, а получено 'три'",
        "параметр «topic» (Тема) не заполнен",
    ]
    assert {problem["code"] for problem in refused.json()["problems"]} == {"bad_param"}

    # Отказ запуска не создаёт: с верными значениями тот же пайплайн запускается.
    assert launch(client, me, pipeline_id, count=5, topic="Логарифмы").status_code == 201


def runs_in_the_database(sessions) -> int:
    async def count() -> int:
        async with sessions() as session:
            return await session.scalar(select(func.count()).select_from(RunRow))

    return asyncio.run(count())


def test_misspelled_field_in_the_launch_request_is_refused(client, me, sessions):
    """Опечатка в `params` не должна молча запустить пайплайн со значениями по умолчанию."""
    pipeline_id = saved(client, me, THREE_FAKES)

    refused = client.post(
        f"{API}/pipelines/{pipeline_id}/runs", json={"parms": {"phrase": "логарифмы"}}, headers=me
    )

    assert refused.status_code == 422
    assert refused.json()["problems"] == [
        {"node": None, "code": "bad_format", "message": "parms: неизвестное поле"}
    ]
    assert runs_in_the_database(sessions) == 0


def test_param_the_database_cannot_store_is_refused_not_crashed(client, me, sessions):
    pipeline_id = saved(client, me, THREE_FAKES)

    refused = launch(client, me, pipeline_id, phrase="лога\x00рифмы")

    assert refused.status_code == 422
    assert "нулевой символ" in refused.json()["message"]
    assert runs_in_the_database(sessions) == 0


def test_block_that_cannot_be_called_yet_is_not_started(client, me, sessions):
    """Блок `mcp` виден валидатору, но MCP-клиента ещё нет: запуск не начинается."""
    pipeline_id = saved(client, me, chain(("mail", "sink.fake_mail")))

    refused = launch(client, me, pipeline_id)

    assert refused.status_code == 422
    assert refused.json()["problems"] == [
        {
            "node": "mail",
            "code": "block_not_callable",
            "message": "блок «sink.fake_mail» пока нечем вызвать",
        }
    ]
    assert runs_in_the_database(sessions) == 0


def test_pipeline_broken_by_a_removed_block_is_not_started(client_of, registry_of, me):
    """Блок убрали после сохранения пайплайна: перед запуском пайплайн проверяется заново."""
    pipeline_id = saved(client_of(registry_of()), me, THREE_FAKES)
    without_upper = client_of(registry_of("source.fake_text", "sink.fake_keep"))

    refused = launch(without_upper, me, pipeline_id)

    assert refused.status_code == 422
    problems = refused.json()["problems"]
    assert [problem["node"] for problem in problems] == ["upper"]
    assert "transform.fake_upper" in problems[0]["message"]


def test_failed_run_is_visible_with_its_error(client, me):
    pipeline_id = saved(
        client, me, chain(("broken", "transform.fake_broken"), ("keep", "sink.fake_keep"))
    )

    run = launch_and_read(client, me, pipeline_id).json()

    assert run["status"] == "error"
    assert run["current"] == ["broken"]
    assert "модель недоступна" in run["error"]
    kinds = [kind for node, kind in journal(client, me, run["id"]) if node == "broken"]
    # Первый вызов и три повтора (ADR 0010): три записи о неудачной попытке и итог.
    assert kinds == ["attempt_failed", "attempt_failed", "attempt_failed", "node_failed"]


def test_run_and_journal_are_visible_only_to_their_teacher(client, me, stranger):
    pipeline_id = saved(client, me, THREE_FAKES)
    run_id = launch(client, me, pipeline_id).json()["id"]

    for path in (f"{API}/runs/{run_id}", f"{API}/runs/{run_id}/events"):
        assert client.get(path, headers=me).status_code == 200
        hidden = client.get(path, headers=stranger)
        assert hidden.status_code == 404
        assert hidden.json() == {"message": "запуск не найден", "problems": []}

    # Чужой пайплайн и запустить нельзя.
    assert launch(client, stranger, pipeline_id).status_code == 404


def test_unknown_run_is_not_found(client, me):
    assert client.get(f"{API}/runs/{uuid.uuid4()}", headers=me).status_code == 404
    assert client.get(f"{API}/runs/{uuid.uuid4()}/events", headers=me).status_code == 404
    assert launch(client, me, uuid.uuid4()).status_code == 404


def test_model_calls_are_tagged_with_run_and_node(client, me, sessions):
    """Открытый вопрос 28: вызов модели из блока записан с запуском и узлом."""
    pipeline_id = saved(
        client, me, chain(("ask", "ai_process.fake_ask"), ("keep", "sink.fake_keep"))
    )

    run = launch_and_read(client, me, pipeline_id, phrase="Сколько будет 2 + 2?").json()

    assert run["status"] == "done", run["error"]
    calls = asyncio.run(LLMCallRepository(sessions).for_run(run["id"]))
    assert [(str(call.run_id), call.node_id, call.provider) for call in calls] == [
        (run["id"], "ask", "fake")
    ]
    assert calls[0].error is None
