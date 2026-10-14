"""Реестр: блоки из папки загружаются, а сломанный блок не мешает остальным.

Блоки создаются во временной папке — так же, как администратор кладёт в папку блок
стороннего автора. Настоящих блоков, базы и модели здесь нет.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from backend.core.contracts.ports import Event, TriggerType
from backend.core.contracts.run import Done
from backend.core.contracts.state import RunStatus
from backend.core.engine import Engine
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.core.validator import tool_problems, validate

TEXT = {"name": "text", "title": "Текст", "type": "Text"}

MAKE = """
from backend.core.contracts.run import Done


async def run(inputs, config, context):
    return Done(outputs={"text": {"text": config["text"]}})
"""

UPPER = """
from backend.core.contracts.run import Done


async def run(inputs, config, context):
    return Done(outputs={"text": {"text": inputs["text"]["text"].upper()}})


def not_async(inputs, config, context):
    return None
"""


class Folder:
    """Папка с блоками на один тест. Имя у каждой своё: Python помнит загруженные модули."""

    def __init__(self, parent: Path) -> None:
        self.root = parent / f"fake_blocks_{uuid.uuid4().hex[:8]}"
        self.root.mkdir()

    def add(self, where: str, block_id: str, code: str | None = MAKE, **fields) -> Path:
        """Кладёт блок в подпапку `where`: манифест и, если нужен, код."""
        folder = self.root / where
        folder.mkdir(parents=True, exist_ok=True)
        if code is not None:
            (folder / "__init__.py").write_text(code, encoding="utf-8")
        module = ".".join([self.root.name, *Path(where).parts])
        manifest = {
            "id": block_id,
            "version": "0.1.0",
            "name": block_id,
            "description": "Фейковый блок для тестов реестра",
            "author": "tests",
            "category": block_id.split(".")[0],
            "runtime": {"type": "python", "entrypoint": f"{module}:run"},
            **fields,
        }
        path = folder / "block.yaml"
        path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
        return path

    def entrypoint(self, where: str, function: str = "run") -> dict:
        module = ".".join([self.root.name, *Path(where).parts])
        return {"type": "python", "entrypoint": f"{module}:{function}"}


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(tmp_path)
    made = Folder(tmp_path)
    yield made
    for name in [name for name in sys.modules if name.startswith(made.root.name)]:
        del sys.modules[name]


def messages(registry) -> list[str]:
    return [problem.message for problem in registry.problems]


def test_blocks_from_a_folder_are_loaded_and_run_by_the_engine(folder, store, graph):
    folder.add("source/make", "source.fake_make", outputs=[TEXT])
    folder.add("transform/upper", "transform.fake_upper", UPPER, inputs=[TEXT], outputs=[TEXT])
    registry = load_registry(folder.root)

    assert registry.problems == []
    assert (
        set(registry.manifests)
        == set(registry.blocks)
        == {
            "source.fake_make",
            "transform.fake_upper",
        }
    )

    pipeline = graph(
        [
            {
                "id": "make",
                "type": "block",
                "block": "source.fake_make",
                "config": {"text": "привет"},
            },
            {
                "id": "upper",
                "type": "block",
                "block": "transform.fake_upper",
                "inputs": {"text": "make.text"},
            },
        ],
        [("make", None, "upper")],
    )
    # Манифесты реестра — валидатору, таблица блоков — движку.
    assert validate(pipeline, registry.manifests).ok
    event = Event(trigger=TriggerType.MANUAL, occurred_at=datetime(2026, 10, 13, tzinfo=UTC))
    state = asyncio.run(
        Engine(store, registry.blocks).start(
            pipeline, run_id="run-1", pipeline_id="pipeline-1", pipeline_version=1, event=event
        )
    )
    assert state.status is RunStatus.DONE
    assert state.ports["upper"]["text"] == {"text": "ПРИВЕТ"}


def test_broken_manifest_does_not_stop_other_blocks(folder):
    broken = folder.add("source/broken", "source.fake_broken", colour="red")
    folder.add("source/make", "source.fake_make", outputs=[TEXT])
    registry = load_registry(folder.root)

    assert set(registry.manifests) == set(registry.blocks) == {"source.fake_make"}
    (problem,) = registry.problems
    assert problem.path == broken
    assert problem.message == "colour: неизвестное поле"
    assert str(problem) == f"{broken}: colour: неизвестное поле"


def test_file_that_is_not_yaml_is_a_problem(folder):
    path = folder.add("source/make", "source.fake_make")
    path.write_text("id: [не закрыта скобка", encoding="utf-8")
    registry = load_registry(folder.root)
    assert registry.manifests == {}
    assert "это не YAML" in messages(registry)[0]


def test_second_block_with_the_same_name_is_refused(folder):
    first = folder.add("source/a", "source.fake_make")
    second = folder.add("source/b", "source.fake_make")
    registry = load_registry(folder.root)

    assert list(registry.manifests) == ["source.fake_make"]
    assert registry.blocks["source.fake_make"].run.__module__.endswith("source.a")
    (problem,) = registry.problems
    assert problem.path == second
    assert problem.message == f"имя блока «source.fake_make» уже занято блоком из {first}"


def test_block_without_code_or_function_is_refused(folder):
    folder.add("source/no_code", "source.fake_no_code", code=None)
    folder.add("source/no_function", "source.fake_no_function", code="VALUE = 1\n")
    folder.add("source/crashes", "source.fake_crashes", code="raise RuntimeError('упал')\n")
    registry = load_registry(folder.root)

    assert registry.manifests == registry.blocks == {}
    crashes, no_code, no_function = messages(registry)
    assert "не загрузился: RuntimeError: упал" in crashes
    assert "нет кода: в папке блока нет файла `__init__.py`" in no_code
    assert "нет функции «run»" in no_function


def test_unreadable_file_and_exiting_code_do_not_stop_other_blocks(folder):
    """Что бы ни было не так с одним блоком, остальные загружаются."""
    windows = folder.add("source/windows", "source.fake_windows")
    windows.write_bytes("description: Блок в кодировке Windows".encode("cp1251"))
    (folder.root / "source" / "folder" / "block.yaml").mkdir(parents=True)
    folder.add("source/exits", "source.fake_exits", code="import sys\n\nsys.exit(1)\n")
    folder.add("source/make", "source.fake_make", outputs=[TEXT])
    registry = load_registry(folder.root)

    assert set(registry.blocks) == {"source.fake_make"}
    exits, not_a_file, encoding = messages(registry)
    assert "не загрузился: SystemExit" in exits
    assert "файл не читается" in not_a_file
    assert encoding == "файл не читается: сохрани его в кодировке UTF-8"


def test_run_must_be_async(folder):
    folder.add(
        "transform/upper",
        "transform.fake_upper",
        UPPER,
        runtime=folder.entrypoint("transform/upper", "not_async"),
    )
    registry = load_registry(folder.root)
    assert registry.manifests == {}
    assert "должна быть объявлена как `async def`" in messages(registry)[0]


@pytest.mark.parametrize("entrypoint", ["os:system", "backend.core.engine:run"])
def test_entrypoint_outside_block_folder_is_refused(folder, entrypoint):
    """Манифест не может назвать блоком чужую функцию."""
    folder.add(
        "source/make", "source.fake_make", runtime={"type": "python", "entrypoint": entrypoint}
    )
    registry = load_registry(folder.root)
    assert registry.manifests == {}
    module = entrypoint.split(":")[0]
    assert (
        f"`entrypoint` указывает на модуль «{module}», а код блока лежит в"
        in (messages(registry)[0])
    )


def test_entrypoint_of_a_neighbour_block_is_refused(folder):
    folder.add("source/make", "source.fake_make")
    folder.add(
        "source/thief", "source.fake_thief", code=None, runtime=folder.entrypoint("source/make")
    )
    registry = load_registry(folder.root)
    assert list(registry.manifests) == ["source.fake_make"]
    assert "а код блока лежит в" in messages(registry)[0]


def test_entrypoint_of_a_nested_block_is_refused(folder):
    """Блок в папке, внутри которой лежит другой блок, не может взять его функцию."""
    folder.add("source/outer/inner", "source.fake_inner")
    outer = folder.add(
        "source/outer",
        "source.fake_outer",
        code=None,
        runtime=folder.entrypoint("source/outer/inner"),
    )
    registry = load_registry(folder.root)

    assert list(registry.manifests) == ["source.fake_inner"]
    (problem,) = registry.problems
    assert problem.path == outer
    assert "а это код другого блока" in problem.message


def test_network_block_is_known_but_not_callable_without_a_connector(folder):
    """Блок `mcp` виден валидатору и редактору; вызвать его можно, когда дан способ вызова."""
    mcp = {"type": "mcp", "server": "email", "tool": "send_email"}
    folder.add("sink/email", "sink.fake_email", code=None, runtime=mcp, side_effects=True)

    registry = load_registry(folder.root)
    assert registry.problems == []
    assert list(registry.manifests) == ["sink.fake_email"]
    assert registry.blocks == {}

    async def send(inputs, config, context):
        return Done()

    seen = []

    def connect(manifest):
        seen.append(manifest.id)
        return send

    registry = load_registry(folder.root, {"mcp": connect})
    assert seen == ["sink.fake_email"]
    assert registry.blocks["sink.fake_email"].run is send


def test_failing_connector_refuses_only_its_block(folder):
    http = {"type": "http", "url": "http://sandbox:8000"}
    folder.add("check/code", "check.fake_code", code=None, runtime=http)
    folder.add("source/make", "source.fake_make", outputs=[TEXT])

    def connect(manifest):
        raise ConnectionError("сервис не отвечает")

    registry = load_registry(folder.root, {"http": connect})
    assert set(registry.manifests) == set(registry.blocks) == {"source.fake_make"}
    assert messages(registry) == [
        "способ вызова «http» не подключил блок: ConnectionError: сервис не отвечает"
    ]


def test_agent_tool_with_side_effects_is_refused(folder):
    mcp = {"type": "mcp", "server": "email", "tool": "send_email"}
    folder.add("sink/email", "sink.fake_email", code=None, runtime=mcp, side_effects=True)
    agent = folder.add(
        "ai_process/agent",
        "ai_process.fake_agent",
        tools=[{"server": "email", "tool": "send_email"}, {"server": "moodle", "tool": "get"}],
    )
    registry = load_registry(folder.root)

    assert list(registry.manifests) == ["sink.fake_email"]
    assert registry.blocks == {}
    (problem,) = registry.problems
    assert problem.path == agent
    assert "агенту разрешён инструмент «email.send_email»" in problem.message


def test_same_data_name_with_another_shape_is_refused(folder):
    """Порты стыкуются по названию данных: одно название — одно описание (ADR 0004)."""

    def report(*fields: str) -> dict:
        schema = {"type": "object", "required": list(fields)}
        return {
            "name": "report",
            "title": "Отчёт",
            "type": "Data",
            "of": "report",
            "schema": schema,
        }

    folder.add("source/a", "source.fake_a", outputs=[report("score")])
    folder.add("source/b", "source.fake_b", outputs=[report("score")])
    other = folder.add("source/c", "source.fake_c", outputs=[report("text")])
    # Блок, который берёт такие данные и сам их не описывает, никому не мешает.
    plain = {"name": "report", "title": "Отчёт", "type": "Data", "of": "report"}
    folder.add("sink/d", "sink.fake_d", inputs=[plain])
    registry = load_registry(folder.root)

    assert set(registry.manifests) == {"source.fake_a", "source.fake_b", "sink.fake_d"}
    (problem,) = registry.problems
    assert problem.path == other
    assert "данные «report» описаны иначе, чем в блоке «source.fake_a»" in problem.message


def test_builtin_blocks_load_without_problems():
    """Сторож для всех будущих блоков: каждый блок в `blocks/` обязан загружаться."""
    registry = load_registry(BUILTIN_BLOCKS)
    assert [str(problem) for problem in registry.problems] == []
    assert set(registry.blocks) == set(registry.manifests)
    assert "source.task_bank" in registry.blocks


def test_example_manifests_give_agents_only_reading_tools(example_manifests):
    for manifest in example_manifests.values():
        assert tool_problems(manifest, example_manifests) == [], manifest.id
