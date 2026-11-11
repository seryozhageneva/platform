"""Запись через хранилище в настоящем запуске: сборка привязывает её к запуску и узлу (ADR 0026)."""

import asyncio
import uuid

from api_fakes import chain, launch_and_read, saved
from sqlalchemy import select

from backend.models.tables import CabinetResultRow


def test_block_publishes_result_bound_to_its_run_and_node(
    client_of, registry_of, sessions, teacher, me
):
    client = client_of(registry_of("source.fake_text", "sink.fake_publish"))
    pipeline_id = saved(client, me, chain(("publish", "sink.fake_publish")))

    run = launch_and_read(client, me, pipeline_id, phrase="итоги урока").json()

    assert run["status"] == "done", run["error"]
    events = client.get(f"/api/v1/runs/{run['id']}/events", headers=me).json()
    (published,) = [event["data"] for event in events if event["type"] == "published"]
    first, again = published["ids"]
    assert first == again

    async def rows():
        async with sessions() as session:
            return (await session.scalars(select(CabinetResultRow))).all()

    (row,) = asyncio.run(rows())
    assert str(row.id) == first
    assert (row.owner_id, row.run_id, row.node_id) == (teacher.id, uuid.UUID(run["id"]), "publish")
    assert (row.student_id, row.content) == (None, {"text": "итоги урока"})
