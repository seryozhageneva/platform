"""Ручной старт через PostgreSQL и настоящий Redis, с фейковыми блоками и моделью."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from api_fakes import THREE_FAKES, chain, launch, saved
from arq.connections import RedisSettings
from arq.worker import Worker

from backend.triggers.queue import (
    JOB_NAME,
    LaunchQueue,
    QueueSettings,
    QueueUnavailable,
    open_queue_connection,
    serialize_job,
)
from backend.triggers.worker import execute_manual, run_manual

API = "/api/v1"
# Только местный Redis из Docker Compose. Каждый тест получает отдельное имя очереди.
TEST_REDIS = RedisSettings(host="127.0.0.1")


@pytest.fixture
def queue_rig(client_of, registry_of):
    queue_name = f"platform:test:{uuid4()}"

    async def enqueue(run_id):
        async with open_queue_connection(TEST_REDIS) as redis:
            await LaunchQueue(redis, name=queue_name).enqueue(run_id)

    return registry_of(), enqueue, queue_name


def run_worker(client, queue_name: str) -> None:
    async def drain():
        worker = Worker(
            [execute_manual],
            queue_name=queue_name,
            redis_settings=TEST_REDIS,
            ctx={"assembly": client.app.state.assembly},
            job_serializer=serialize_job,
            job_deserializer=json.loads,
            burst=True,
            handle_signals=False,
            poll_delay=0.01,
            retry_jobs=False,
            max_tries=1,
            keep_result=0,
        )
        try:
            assert await worker.run_check() == 1
        finally:
            await worker.close()

    asyncio.run(drain())


def read_run(client, me, run_id):
    response = client.get(f"{API}/runs/{run_id}", headers=me)
    assert response.status_code == 200, response.text
    return response.json()


def event_types(client, me, run_id):
    return [event["type"] for event in client.get(f"{API}/runs/{run_id}/events", headers=me).json()]


def test_post_returns_before_arq_runs_the_saved_version(client_of, me, queue_rig):
    registry, enqueue, queue_name = queue_rig
    client = client_of(registry, enqueue=enqueue)
    pipeline_id = saved(client, me, THREE_FAKES)

    response = launch(client, me, pipeline_id)
    assert response.status_code == 201, response.text
    queued = response.json()
    run_id = queued["id"]
    assert queued["status"] == "running"
    assert read_run(client, me, run_id) == queued
    assert event_types(client, me, run_id) == ["run_queued"]

    async def check_job():
        async with open_queue_connection(TEST_REDIS) as redis:
            [job] = await redis.queued_jobs(queue_name=queue_name)
            assert (job.job_id, job.function, job.args, job.kwargs) == (
                run_id,
                JOB_NAME,
                [run_id],
                {},
            )

    asyncio.run(check_job())
    changed = chain(("keep", "sink.fake_keep"))
    assert client.put(f"{API}/pipelines/{pipeline_id}", headers=me, json=changed).status_code == 200

    run_worker(client, queue_name)
    finished = read_run(client, me, run_id)
    assert (finished["status"], finished["pipeline_version"]) == ("done", 1)
    events = event_types(client, me, run_id)
    assert events[:2] == ["run_queued", "run_started"]
    assert events.count("node_done") == 3
    assert events[-1] == "run_done"

    # Redis уже забыл результат: намеренно доставляем тот же идентификатор заново.
    asyncio.run(enqueue(UUID(run_id)))
    run_worker(client, queue_name)
    assert event_types(client, me, run_id) == events


def test_lost_queue_ack_rolls_back_even_if_redis_received_the_job(client_of, me, queue_rig):
    registry, enqueue, queue_name = queue_rig

    async def lost_ack(run_id):
        await enqueue(run_id)
        raise QueueUnavailable

    client = client_of(registry, enqueue=lost_ack)
    pipeline_id = saved(client, me, THREE_FAKES)

    response = launch(client, me, pipeline_id)
    assert response.status_code == 503, response.text
    assert response.json()["problems"][0]["code"] == "queue_unavailable"
    run_worker(client, queue_name)
    assert client.get(f"{API}/runs", headers=me).json() == []


def test_worker_timeout_records_an_error_and_prevents_a_second_start(client, me, monkeypatch):
    pipeline_id = saved(client, me, THREE_FAKES)
    response = launch(client, me, pipeline_id)
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    assembly = client.app.state.assembly
    engine = assembly.engine()
    execute = engine.execute_prepared

    async def interrupted(pipeline, state, trigger_type):
        await asyncio.sleep(30)
        await execute(pipeline, state, trigger_type)

    monkeypatch.setattr(assembly, "engine", lambda: engine)
    monkeypatch.setattr(engine, "execute_prepared", interrupted)
    asyncio.run(run_manual(assembly, UUID(run_id), timeout=0.01))

    failed = read_run(client, me, run_id)
    assert failed["status"] == "error"
    assert failed["error"] == "Истекло время выполнения фонового запуска"
    events = ["run_queued", "worker_failed"]
    assert event_types(client, me, run_id) == events

    monkeypatch.setattr(engine, "execute_prepared", execute)
    asyncio.run(run_manual(assembly, UUID(run_id)))
    assert event_types(client, me, run_id) == events


def test_worker_finishes_a_pipeline_with_only_a_trigger(client, me):
    graph = {
        "format": 1,
        "id": "trigger_only",
        "name": "Только триггер",
        "nodes": [{"id": "start", "type": "trigger", "launches": [{"type": "manual"}]}],
    }
    pipeline_id = saved(client, me, graph)
    response = launch(client, me, pipeline_id)
    assert response.status_code == 201, response.text
    queued = response.json()
    assert queued["status"] == "running" and queued["current"] == []
    run_id = queued["id"]
    asyncio.run(run_manual(client.app.state.assembly, UUID(run_id)))
    assert read_run(client, me, run_id)["status"] == "done"
    assert event_types(client, me, run_id) == ["run_queued", "run_started", "run_done"]


def test_redis_url_has_the_same_supported_settings_for_api_and_worker():
    settings = QueueSettings(
        redis_url="rediss://queue:fake%40password@redis.example.test:6380/2"
    ).connection_settings()
    assert (settings.host, settings.port, settings.database) == ("redis.example.test", 6380, 2)
    assert settings.username == "queue" and settings.password == "fake@password"
    assert settings.ssl and settings.ssl_check_hostname
    with pytest.raises(RuntimeError, match="без параметров запроса"):
        QueueSettings(
            redis_url="rediss://redis.example.test/0?ssl_ca_certs=ca.pem"
        ).connection_settings()
