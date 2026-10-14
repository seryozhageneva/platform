"""Подделки для тестов API: фейковые блоки, пайплайны из них и сохранение запросом.

Фейковые блоки создаются во временной папке — так же, как администратор кладёт в папку блок
стороннего автора. Настоящий блок из `blocks/` проверяется в `test_tasks_api.py`.
"""

from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

TEXT = {"name": "text", "title": "Текст", "type": "Text"}

MAKE = """
from backend.core.contracts.run import BlockEvent, Done


async def run(inputs, config, context):
    return Done(outputs={"text": {"text": config["text"]}}, events=[BlockEvent(type="text_made")])
"""

UPPER = """
from backend.core.contracts.run import Done


async def run(inputs, config, context):
    return Done(outputs={"text": {"text": inputs["text"]["text"].upper()}})
"""

KEEP = """
from backend.core.contracts.run import BlockEvent, Done


async def run(inputs, config, context):
    text = inputs["text"]["text"]
    return Done(events=[BlockEvent(type="text_kept", data={"text": text})])
"""

ASK = """
from backend.core.contracts.interfaces import LLMMessage
from backend.core.contracts.run import Done


async def run(inputs, config, context):
    reply = await context.llm.complete([LLMMessage(role="user", content=inputs["text"]["text"])])
    return Done(outputs={"text": {"text": reply.text}})
"""

BANK = """
from backend.core.contracts.run import BlockEvent, Done


async def run(inputs, config, context):
    tasks = await context.store.find_tasks()
    return Done(events=[BlockEvent(type="tasks_seen", data={"ids": [task.id for task in tasks]})])
"""

BROKEN = """
async def run(inputs, config, context):
    raise RuntimeError("модель недоступна")
"""

# Имя блока -> (код, поля манифеста).
FAKE_BLOCKS: dict[str, tuple[str | None, dict[str, Any]]] = {
    "source.fake_text": (
        MAKE,
        {
            "outputs": [TEXT],
            "config": {"type": "object", "properties": {"text": {"type": "string"}}},
        },
    ),
    "transform.fake_upper": (UPPER, {"inputs": [TEXT], "outputs": [TEXT]}),
    "sink.fake_keep": (KEEP, {"inputs": [TEXT]}),
    # Блок с последствиями: без Подтверждения перед ним валидатор предупреждает.
    "sink.fake_send": (KEEP, {"inputs": [TEXT], "side_effects": True}),
    "ai_process.fake_ask": (ASK, {"inputs": [TEXT], "outputs": [TEXT]}),
    # Читает банк через хранилище платформы и пишет в журнал, какие задачи увидел.
    "source.fake_bank": (BANK, {}),
    "transform.fake_broken": (BROKEN, {"inputs": [TEXT], "outputs": [TEXT]}),
    # Блок-обёртка над MCP-инструментом: MCP-клиента ещё нет, вызвать его нечем.
    "sink.fake_mail": (
        None,
        {"inputs": [TEXT], "runtime": {"type": "mcp", "server": "email", "tool": "send"}},
    ),
}


def write_blocks(root: Path, names: list[str]) -> None:
    for block_id in names:
        code, fields = FAKE_BLOCKS[block_id]
        category, name = block_id.split(".")
        folder = root / category / name
        folder.mkdir(parents=True)
        if code is not None:
            (folder / "__init__.py").write_text(code, encoding="utf-8")
        manifest = {
            "id": block_id,
            "version": "0.1.0",
            "name": name,
            "description": "Фейковый блок для тестов API",
            "author": "tests",
            "category": category,
            "runtime": {"type": "python", "entrypoint": f"{root.name}.{category}.{name}:run"},
            **fields,
        }
        (folder / "block.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8"
        )


def chain(*steps: tuple[str, str], launches: tuple[str, ...] = ("manual",)) -> dict[str, Any]:
    """Пайплайн-цепочка: «сделать текст» и за ним названные блоки, каждый читает предыдущий.

    `steps` — пары (узел, блок). Текст берётся из параметра `phrase`.
    """
    nodes: list[dict[str, Any]] = [
        {"id": "start", "type": "trigger", "launches": [{"type": kind} for kind in launches]},
        {
            "id": "make",
            "type": "block",
            "block": "source.fake_text",
            "config": {"text": {"$param": "phrase"}},
        },
    ]
    transitions = [{"from": "start", "to": "make"}]
    previous = "make"
    for node_id, block in steps:
        nodes.append(
            {"id": node_id, "type": "block", "block": block, "inputs": {"text": f"{previous}.text"}}
        )
        transitions.append({"from": previous, "to": node_id})
        previous = node_id
    return {
        "format": 1,
        "id": "chain",
        "name": "Цепочка фейковых блоков",
        "params": [{"name": "phrase", "title": "Фраза", "type": "string", "default": "привет"}],
        "nodes": nodes,
        "transitions": transitions,
    }


THREE_FAKES = chain(("upper", "transform.fake_upper"), ("keep", "sink.fake_keep"))


def saved(client: TestClient, headers: dict[str, str], pipeline: dict[str, Any]) -> str:
    """Сохраняет пайплайн запросом и возвращает его идентификатор."""
    response = client.post("/api/v1/pipelines", json=pipeline, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def launch(client: TestClient, headers: dict[str, str], pipeline_id: str, **params: Any):
    """Запускает пайплайн вручную с указанными параметрами; возвращает ответ сервера."""
    return client.post(
        f"/api/v1/pipelines/{pipeline_id}/runs", json={"params": params}, headers=headers
    )
