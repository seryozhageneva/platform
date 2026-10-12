"""Репозиторий пайплайнов: граф хранится без потерь, каждое сохранение — новая версия."""

import asyncio
import uuid
from pathlib import Path

import pytest

from backend.core.contracts.pipeline import load_pipeline
from backend.models.pipelines import PipelineRepository

PIPELINES = Path(__file__).resolve().parents[2] / "docs" / "examples" / "pipelines"
SCENARIOS = [
    "scenario-1-training",
    "scenario-2-grading",
    "scenario-3-materials",
    "scenario-4-analytics",
]


def scenario_pipeline(name: str = "scenario-1-training"):
    return load_pipeline(PIPELINES / f"{name}.json")


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_is_stored_and_read_back_unchanged(sessions, teacher, name):
    original = scenario_pipeline(name)

    async def scenario():
        pipelines = PipelineRepository(sessions)
        row = await pipelines.create(teacher.id, original)

        assert (row.slug, row.name, row.latest_version) == (original.id, original.name, 1)
        assert await pipelines.load(row.id) == original
        assert await pipelines.load(row.id, version=1) == original

    asyncio.run(scenario())


def test_saving_again_makes_a_new_version_and_keeps_the_old_one(sessions, teacher):
    first = scenario_pipeline()
    second = first.model_copy(update={"name": "Тренировка, вторая редакция"})

    async def scenario():
        pipelines = PipelineRepository(sessions)
        row = await pipelines.create(teacher.id, first)

        assert await pipelines.save_version(teacher.id, row.id, second) == 2

        assert await pipelines.load(row.id, version=1) == first
        assert await pipelines.load(row.id, version=2) == second
        assert await pipelines.load(row.id) == second
        stored = await pipelines.get(teacher.id, row.id)
        assert (stored.latest_version, stored.name) == (2, "Тренировка, вторая редакция")

    asyncio.run(scenario())


def test_unknown_pipeline_or_version_is_none(sessions, teacher):
    async def scenario():
        pipelines = PipelineRepository(sessions)
        row = await pipelines.create(teacher.id, scenario_pipeline())

        assert await pipelines.load(row.id, version=7) is None
        assert await pipelines.load(uuid.uuid4()) is None
        assert await pipelines.get(teacher.id, uuid.uuid4()) is None

    asyncio.run(scenario())


def test_teacher_sees_and_changes_only_own_pipelines(sessions, teacher, other_teacher):
    async def scenario():
        pipelines = PipelineRepository(sessions)
        own = await pipelines.create(teacher.id, scenario_pipeline())
        foreign = await pipelines.create(
            other_teacher.id, scenario_pipeline("scenario-3-materials")
        )

        assert [row.id for row in await pipelines.list_pipelines(teacher.id)] == [own.id]
        assert await pipelines.get(teacher.id, foreign.id) is None
        with pytest.raises(LookupError):
            await pipelines.save_version(teacher.id, foreign.id, scenario_pipeline())
        # Чужая попытка ничего не изменила.
        assert (await pipelines.get(other_teacher.id, foreign.id)).latest_version == 1

    asyncio.run(scenario())


def test_two_teachers_can_keep_pipelines_with_the_same_name(sessions, teacher, other_teacher):
    """Поле `id` из файла пайплайна — читаемое имя, а не ключ в базе."""

    async def scenario():
        pipelines = PipelineRepository(sessions)
        first = await pipelines.create(teacher.id, scenario_pipeline())
        second = await pipelines.create(other_teacher.id, scenario_pipeline())
        assert first.slug == second.slug
        assert first.id != second.id

    asyncio.run(scenario())
