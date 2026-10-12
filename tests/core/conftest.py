"""Общее для тестов движка: три фейковых блока, пайплайн из них и хранилище «в памяти».

Фейковый блок — простая подделка настоящего блока с тем же контрактом: манифест и функция
`run`. Настоящих блоков, базы и ИИ-модели здесь нет (ADR 0006).
"""

from typing import Any

import pytest

from backend.core.contracts.manifest import Manifest, parse_manifest
from backend.core.contracts.pipeline import Pipeline, parse_pipeline
from backend.core.contracts.run import BlockEvent, Done, RunContext
from backend.core.contracts.state import RunState
from backend.core.engine import LoadedBlock

TEXT_IN = {"name": "text", "title": "Текст", "type": "Text"}
TEXT_OUT = {"name": "text", "title": "Текст", "type": "Text"}


def fake_manifest(block_id: str, **fields: Any) -> Manifest:
    category, name = block_id.split(".")
    return parse_manifest(
        {
            "id": block_id,
            "version": "0.1.0",
            "name": name,
            "description": "Фейковый блок для тестов движка",
            "author": "tests",
            "category": category,
            "runtime": {"type": "python", "entrypoint": f"tests.core.conftest:{name}"},
            **fields,
        }
    )


class MemoryRunStore:
    """Хранилище запусков «в памяти» с тем же интерфейсом `RunStore`, что и у базы.

    Состояние хранится текстом JSON, как в базе: значение, которое нельзя записать в JSON,
    не пройдёт и здесь, а сохранённая копия не меняется вслед за состоянием в движке.
    """

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        # Все сохранения по порядку — чтобы тест видел, как запуск двигался по узлам.
        self.saved: list[RunState] = []
        self.journal: list[tuple[str, str, dict[str, Any]]] = []

    async def load(self, run_id: str) -> RunState | None:
        raw = self._states.get(run_id)
        return None if raw is None else RunState.model_validate_json(raw)

    async def save(self, state: RunState) -> None:
        raw = state.model_dump_json()
        self._states[state.run_id] = raw
        self.saved.append(RunState.model_validate_json(raw))

    async def append_events(self, run_id: str, node_id: str, events: list[BlockEvent]) -> None:
        assert run_id in self._states, "событие пишется только для существующего запуска"
        for event in events:
            self.journal.append((node_id, event.type, event.model_dump(mode="json")["data"]))


class StrictMemoryRunStore(MemoryRunStore):
    """Как PostgreSQL: текст с нулевым символом не записывает ни в состояние, ни в журнал."""

    async def save(self, state: RunState) -> None:
        if "\\u0000" in state.model_dump_json():
            raise RuntimeError("хранилище не записывает нулевой символ")
        await super().save(state)

    async def append_events(self, run_id: str, node_id: str, events: list[BlockEvent]) -> None:
        if any("\\u0000" in event.model_dump_json() for event in events):
            raise RuntimeError("хранилище не записывает нулевой символ")
        await super().append_events(run_id, node_id, events)


@pytest.fixture
def strict_store() -> StrictMemoryRunStore:
    return StrictMemoryRunStore()


@pytest.fixture
def manifest_for():
    """Манифест для фейкового блока, которого нет среди трёх готовых."""
    return fake_manifest


@pytest.fixture
def store() -> MemoryRunStore:
    return MemoryRunStore()


@pytest.fixture
def calls() -> list[tuple[str, dict[str, Any], dict[str, Any], RunContext]]:
    """Журнал вызовов фейковых блоков: (узел, входы, настройки, context)."""
    return []


@pytest.fixture
def blocks(calls) -> dict[str, LoadedBlock]:
    """Три фейковых блока: «сделать текст» → «в верхний регистр» → «сохранить»."""

    async def make_text(inputs, config, context):
        calls.append((context.node_id, inputs, config, context))
        return Done(
            outputs={"text": {"text": config["text"]}}, events=[BlockEvent(type="text_made")]
        )

    async def upper(inputs, config, context):
        calls.append((context.node_id, inputs, config, context))
        return Done(outputs={"text": {"text": inputs["text"]["text"].upper()}})

    async def keep(inputs, config, context):
        calls.append((context.node_id, inputs, config, context))
        text = inputs["text"]["text"]
        return Done(
            outputs={"report": {"text": text, "length": len(text)}},
            events=[BlockEvent(type="text_kept", data={"length": len(text)})],
        )

    return {
        "source.fake_text": LoadedBlock(
            fake_manifest(
                "source.fake_text",
                outputs=[TEXT_OUT],
                config={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
            make_text,
        ),
        "transform.fake_upper": LoadedBlock(
            fake_manifest("transform.fake_upper", inputs=[TEXT_IN], outputs=[TEXT_OUT]), upper
        ),
        "sink.fake_keep": LoadedBlock(
            fake_manifest(
                "sink.fake_keep",
                inputs=[
                    TEXT_IN,
                    {"name": "event", "title": "Событие", "type": "Event", "required": False},
                ],
                outputs=[{"name": "report", "title": "Отчёт", "type": "Data", "of": "report"}],
            ),
            keep,
        ),
    }


@pytest.fixture
def pipeline_data() -> dict[str, Any]:
    """Пайплайн из трёх фейковых блоков как словарь — свежая копия, которую тест может менять."""
    return {
        "format": 1,
        "id": "three_fakes",
        "name": "Три фейковых блока",
        "params": [{"name": "phrase", "title": "Фраза", "type": "string", "default": "привет"}],
        "nodes": [
            {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
            {
                "id": "make",
                "type": "block",
                "block": "source.fake_text",
                "config": {"text": {"$param": "phrase"}},
            },
            {
                "id": "upper",
                "type": "block",
                "block": "transform.fake_upper",
                "inputs": {"text": "make.text"},
            },
            {
                "id": "keep",
                "type": "block",
                "block": "sink.fake_keep",
                "inputs": {"text": "upper.text", "event": "start.event"},
            },
        ],
        "transitions": [
            {"from": "start", "to": "make"},
            {"from": "make", "to": "upper"},
            {"from": "upper", "to": "keep"},
        ],
    }


@pytest.fixture
def pipeline(pipeline_data) -> Pipeline:
    return parse_pipeline(pipeline_data)
