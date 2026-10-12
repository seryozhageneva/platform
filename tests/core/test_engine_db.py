"""Движок с настоящим хранилищем: состояние запуска лежит в PostgreSQL.

Это проверка критерия задачи 04 «состояние в БД». Движок базу не подключает: готовое
хранилище `PgRunStore` ему передаёт тест — так же, как в платформе это сделает слой сборки.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.run import BlockEvent, Done
from backend.core.contracts.state import RunStatus
from backend.core.engine import Engine, LoadedBlock
from backend.models.pipelines import PipelineRepository
from backend.models.run_store import PgRunStore
from backend.models.tables import RunRow

EVENT = Event(trigger=TriggerType.MANUAL, occurred_at=datetime(2026, 10, 12, 9, 30, tzinfo=UTC))


def test_state_is_in_the_database(sessions, teacher, blocks, pipeline):
    run_id = str(uuid.uuid4())

    async def scenario():
        saved = await PipelineRepository(sessions).create(teacher.id, pipeline)
        state = await Engine(PgRunStore(sessions), blocks).start(
            pipeline,
            run_id=run_id,
            pipeline_id=str(saved.id),
            pipeline_version=1,
            event=EVENT,
            teacher_id=str(teacher.id),
        )
        assert state.status is RunStatus.DONE

        # Новое хранилище — как после перезапуска сервера: всё читается из базы.
        store = PgRunStore(sessions)
        assert await store.load(run_id) == state
        async with sessions() as session:
            row = await session.get(RunRow, uuid.UUID(run_id))
        assert row.status == RunStatus.DONE
        assert row.state["current"] == []
        assert row.state["ports"]["make"] == {"text": {"text": "привет"}}
        assert row.state["ports"]["upper"] == {"text": {"text": "ПРИВЕТ"}}
        assert row.state["ports"]["keep"] == {"report": {"text": "ПРИВЕТ", "length": 6}}

        journal = await store.events(run_id)
        assert [(event.node_id, event.type) for event in journal] == [
            ("start", "run_started"),
            ("make", "text_made"),
            ("make", "node_done"),
            ("upper", "node_done"),
            ("keep", "text_kept"),
            ("keep", "node_done"),
            ("keep", "run_done"),
        ]

    asyncio.run(scenario())


def test_run_continues_from_the_database_after_a_failure(
    sessions, teacher, blocks, pipeline, calls
):
    run_id = str(uuid.uuid4())

    async def broken(inputs, config, context):
        raise RuntimeError("модель недоступна")

    upper = blocks["transform.fake_upper"]
    with_broken = {**blocks, "transform.fake_upper": LoadedBlock(upper.manifest, broken)}

    async def scenario():
        saved = await PipelineRepository(sessions).create(teacher.id, pipeline)
        failed = await Engine(PgRunStore(sessions), with_broken).start(
            pipeline, run_id=run_id, pipeline_id=str(saved.id), pipeline_version=1, event=EVENT
        )
        assert failed.status is RunStatus.ERROR

        async with sessions() as session:
            row = await session.get(RunRow, uuid.UUID(run_id))
        assert row.status == RunStatus.ERROR
        assert row.error.startswith("узел «upper»: блок «transform.fake_upper» упал")
        assert row.state["current"] == ["upper"]

        # Другой движок и другое хранилище: о запуске известно только то, что в базе.
        state = await Engine(PgRunStore(sessions), blocks).resume(pipeline, run_id)

        assert state.status is RunStatus.DONE and state.error is None
        assert await PgRunStore(sessions).load(run_id) == state
        assert [node for node, *_ in calls] == ["make", "upper", "keep"]

    asyncio.run(scenario())


def test_output_the_database_rejects_stops_the_run(sessions, teacher, blocks, pipeline, calls):
    """Нулевой символ PostgreSQL в JSON-поле не записывает — так бывает в тексте из PDF."""
    run_id = str(uuid.uuid4())

    async def with_zero(inputs, config, context):
        return Done(outputs={"text": {"text": "при\x00вет"}})

    upper = blocks["transform.fake_upper"]
    with_bad = {**blocks, "transform.fake_upper": LoadedBlock(upper.manifest, with_zero)}

    async def scenario():
        saved = await PipelineRepository(sessions).create(teacher.id, pipeline)
        failed = await Engine(PgRunStore(sessions), with_bad).start(
            pipeline, run_id=run_id, pipeline_id=str(saved.id), pipeline_version=1, event=EVENT
        )

        # Запуск не остался «выполняться»: в базе статус «ошибка», выходов узла нет.
        assert failed.status is RunStatus.ERROR
        assert failed.error.startswith("узел «upper»: не удалось сохранить состояние после узла")
        assert await PgRunStore(sessions).load(run_id) == failed
        async with sessions() as session:
            row = await session.get(RunRow, uuid.UUID(run_id))
        assert row.status == RunStatus.ERROR
        assert row.state["current"] == ["upper"]
        assert sorted(row.state["ports"]) == ["make", "start"]

        state = await Engine(PgRunStore(sessions), blocks).resume(pipeline, run_id)
        assert state.status is RunStatus.DONE
        assert [node for node, *_ in calls] == ["make", "upper", "keep"]

    asyncio.run(scenario())


def test_error_text_the_database_rejects_still_stops_the_run(sessions, teacher, blocks, pipeline):
    """Блок процитировал в ошибке текст с нулевым символом: в базе всё равно статус «ошибка»."""
    run_id = str(uuid.uuid4())

    async def broken(inputs, config, context):
        raise ValueError("не разобрать текст: при\x00вет")

    upper = blocks["transform.fake_upper"]
    with_broken = {**blocks, "transform.fake_upper": LoadedBlock(upper.manifest, broken)}

    async def scenario():
        saved = await PipelineRepository(sessions).create(teacher.id, pipeline)
        failed = await Engine(PgRunStore(sessions), with_broken).start(
            pipeline, run_id=run_id, pipeline_id=str(saved.id), pipeline_version=1, event=EVENT
        )
        assert failed.status is RunStatus.ERROR

        store = PgRunStore(sessions)
        assert await store.load(run_id) == failed
        async with sessions() as session:
            row = await session.get(RunRow, uuid.UUID(run_id))
        assert row.status == RunStatus.ERROR
        assert row.error.endswith("ValueError: не разобрать текст: при\ufffdвет")
        assert [event.type for event in await store.events(run_id)][-1] == "node_failed"

        state = await Engine(PgRunStore(sessions), blocks).resume(pipeline, run_id)
        assert state.status is RunStatus.DONE

    asyncio.run(scenario())


def test_block_event_the_database_rejects_does_not_break_the_run(
    sessions, teacher, blocks, pipeline
):
    run_id = str(uuid.uuid4())
    keep = blocks["sink.fake_keep"]

    async def with_bad_event(inputs, config, context):
        done = await keep.run(inputs, config, context)
        return done.model_copy(update={"events": [BlockEvent(type="note", data={"t": "\x00"})]})

    with_bad = {**blocks, "sink.fake_keep": LoadedBlock(keep.manifest, with_bad_event)}

    async def scenario():
        saved = await PipelineRepository(sessions).create(teacher.id, pipeline)
        state = await Engine(PgRunStore(sessions), with_bad).start(
            pipeline, run_id=run_id, pipeline_id=str(saved.id), pipeline_version=1, event=EVENT
        )
        assert state.status is RunStatus.DONE

        store = PgRunStore(sessions)
        assert await store.load(run_id) == state
        journal = [(event.node_id, event.type) for event in await store.events(run_id)]
        assert journal[-3:] == [
            ("keep", "events_lost"),
            ("keep", "node_done"),
            ("keep", "run_done"),
        ]

    asyncio.run(scenario())
