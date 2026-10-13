"""Общее для тестов движка: фейковые блоки, пайплайны из них и хранилище «в памяти».

Фейковый блок — простая подделка настоящего блока с тем же контрактом: манифест и функция
`run`. Настоящих блоков, базы и ИИ-модели здесь нет (ADR 0006).
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.core.contracts.manifest import Manifest, load_manifest, parse_manifest
from backend.core.contracts.pipeline import Pipeline, parse_pipeline
from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.run import BlockEvent, Done, RunContext, Waiting
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState
from backend.core.engine import Engine, LoadedBlock

RUN = {"run_id": "run-1", "pipeline_id": "pipeline-1", "pipeline_version": 1}
EVENT = Event(trigger=TriggerType.MANUAL, occurred_at=datetime(2026, 10, 12, 9, 30, tzinfo=UTC))

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


# --- Для тестов конструкций движка v2 ------------------------------------------------------


class Runner:
    """Запускает движок в тесте. На каждое действие — новый экземпляр движка.

    Так каждый тест заодно проверяет, что движок ничего не держит в памяти: всё, что нужно
    для продолжения запуска, лежит в хранилище.
    """

    def __init__(self, store: MemoryRunStore, blocks: Mapping[str, LoadedBlock]) -> None:
        self.store = store
        self.blocks = blocks

    def start(self, pipeline: Pipeline, **more: Any) -> RunState:
        engine = Engine(self.store, self.blocks)
        return asyncio.run(engine.start(pipeline, **{**RUN, "event": EVENT, **more}))

    def resume(self, pipeline: Pipeline, run_id: str = "run-1") -> RunState:
        return asyncio.run(Engine(self.store, self.blocks).resume(pipeline, run_id))

    def respond(
        self, pipeline: Pipeline, node_id: str, response: dict[str, Any], run_id: str = "run-1"
    ) -> RunState:
        engine = Engine(self.store, self.blocks)
        return asyncio.run(engine.respond(pipeline, run_id, node_id, response))

    def interrupted(self, **fields: Any) -> RunState:
        """Кладёт в хранилище запуск, прерванный посреди работы, — как после сбоя сервера."""
        state = RunState(**{**RUN, **fields})
        asyncio.run(self.store.save(state))
        return state

    def journal(self, *kinds: str) -> list[tuple[str, str, dict[str, Any]]]:
        """Записи журнала указанных видов, по порядку."""
        return [entry for entry in self.store.journal if entry[1] in kinds]


@pytest.fixture
def go(store, blocks) -> Runner:
    return Runner(store, blocks)


@pytest.fixture
def add_block(blocks, calls):
    """Добавляет фейковый блок в таблицу блоков. Каждый его вызов попадает в `calls`."""

    def add(block_id: str, run, **manifest_fields: Any) -> None:
        async def recorded(inputs, config, context):
            calls.append((context.node_id, inputs, config, context))
            return await run(inputs, config, context)

        blocks[block_id] = LoadedBlock(fake_manifest(block_id, **manifest_fields), recorded)

    return add


@pytest.fixture
def called(calls):
    """Узлы, блоки которых вызывались, по порядку."""
    return lambda: [node for node, *_ in calls]


@pytest.fixture
def graph():
    """Собирает пайплайн: триггер `start`, переход от него к первому узлу и всё переданное.

    Переход записывается коротко: `("откуда", "исход", "куда")`; исход None — «при любом».
    """

    def build(nodes: list[dict], transitions: list[tuple] = (), params: list[dict] = ()):
        moves = [
            {"from": source, "to": target} | ({"when": when} if when else {})
            for source, when, target in transitions
        ]
        return parse_pipeline(
            {
                "id": "test_graph",
                "name": "Пайплайн для теста",
                "params": list(params),
                "nodes": [
                    {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
                    *nodes,
                ],
                "transitions": [{"from": "start", "to": nodes[0]["id"]}, *moves],
            }
        )

    return build


def body(start: str, nodes: list[dict], transitions: list[tuple] = ()) -> dict[str, Any]:
    """Тело «для каждого» в формате пайплайна; переходы — как в `graph`."""
    return {
        "start": start,
        "nodes": nodes,
        "transitions": [
            {"from": source, "to": target} | ({"when": when} if when else {})
            for source, when, target in transitions
        ],
    }


@pytest.fixture
def for_each_body():
    return body


ANSWER_OUT = {"name": "answer", "title": "Ответ", "type": "Answer"}
QUESTION = {"task_id": "t1", "statement": "Вычислите $2^3$.", "forms": ["text"]}


def answer(text: str) -> dict[str, Any]:
    """Ответ ученика с экрана «форма ответа»."""
    return {"action": "answer", "answer": {"task_id": "t1", "form": "text", "text": text}}


@pytest.fixture
def answer_with():
    return answer


@pytest.fixture
def ask(add_block):
    """Блок `student.fake_ask`: показывает ученику вопрос и ждёт ответа.

    Первый вызов — «жду человека». Второй, с ответом, — «готово»: ответ уходит на выход,
    исход — `answer` или `hint_requested`.
    """

    async def run(inputs, config, context):
        if context.human_response is None:
            return Waiting(screen=ScreenType.ANSWER_FORM, data=QUESTION)
        if context.human_response["action"] == "hint":
            return Done(outcome="hint_requested")
        return Done(outputs={"answer": context.human_response["answer"]}, outcome="answer")

    add_block(
        "student.fake_ask",
        run,
        kind="interactive",
        screen="answer_form",
        inputs=[{**TEXT_IN, "required": False}],
        outputs=[ANSWER_OUT],
        outcomes=["answer", "hint_requested"],
    )


FILES_OUT = {"name": "files", "title": "Файлы", "type": "File", "list": True}


def file_ref(name: str) -> dict[str, Any]:
    """Ссылка на файл работы: код, если имя кончается на `.py`, иначе документ."""
    kind = "code" if name.endswith(".py") else "document"
    return {"id": name, "name": name, "kind": kind, "media_type": "text/plain"}


@pytest.fixture
def file_of():
    return file_ref


@pytest.fixture
def files(add_block):
    """Блок `source.fake_files`: список файлов с именами из настройки `names`."""

    async def run(inputs, config, context):
        return Done(outputs={"files": [file_ref(name) for name in config["names"]]})

    add_block("source.fake_files", run, outputs=[FILES_OUT])

    def node(*names: str) -> dict[str, Any]:
        config = {"names": list(names)}
        return {"id": "get", "type": "block", "block": "source.fake_files", "config": config}

    return node


# --- Для тестов реестра и валидатора -------------------------------------------------------

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"


@pytest.fixture
def example_manifests() -> dict[str, Manifest]:
    """Манифесты из `docs/examples/manifests/` — свежий словарь, который тест может менять."""
    loaded = [load_manifest(path) for path in sorted((EXAMPLES / "manifests").glob("*.yaml"))]
    return {manifest.id: manifest for manifest in loaded}


@pytest.fixture
def scenario():
    """Сценарий по номеру как словарь — свежая копия, которую тест может портить."""

    def load(number: int) -> dict[str, Any]:
        (path,) = (EXAMPLES / "pipelines").glob(f"scenario-{number}-*.json")
        return json.loads(path.read_text(encoding="utf-8"))

    return load
