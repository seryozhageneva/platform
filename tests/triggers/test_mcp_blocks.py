"""MCP-клиент и блоки `runtime: mcp` на сервере Moodle в том же процессе (ADR 0028).

Сервер — настоящий MCP-сервер Moodle, только ходит он в подделку Moodle, а клиент
подключается к нему без дочерней программы. Хранилище — подделка из контракта.
"""

import asyncio
import base64
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from backend.core.contracts.interfaces import ToolClient
from backend.core.contracts.ports import FileRef
from backend.core.contracts.run import Done, RunContext
from backend.core.contracts.testing import FakeStore
from backend.core.registry import BUILTIN_BLOCKS, load_registry
from backend.mcp_client.client import McpToolClient, ToolCallError, builtin_server
from backend.triggers.mcp_blocks import mcp_connector
from mcp_servers.moodle.testing import FILES, TOKEN, FakeMoodle, fake_server, make_submission

CONFIG = {"course_id": 2, "assignment_id": 1}


def context(store=None, teacher="00000000-0000-0000-0000-000000000001") -> RunContext:
    return RunContext(
        run_id="r", node_id="get_works", pipeline_id="p", teacher_id=teacher, store=store
    )


def registry_with(server, seen=None):
    async def tools_for(owner_id, name):
        if seen is not None:
            seen.append((owner_id, name))
        return McpToolClient({name: server})

    return load_registry(BUILTIN_BLOCKS, {"mcp": mcp_connector(tools_for)})


def writer_server() -> MCPServer:
    """Сервер, у которого инструмент меняет внешнюю систему."""
    server = MCPServer("moodle")

    @server.tool(name="get_submissions", annotations=ToolAnnotations(read_only_hint=False))
    async def get_submissions(course_id: int, assignment_id: int) -> dict[str, Any]:
        return {"works": [], "outcome": "empty"}

    return server


def test_client_has_contract_interface_and_reports_read_only():
    client = McpToolClient({"moodle": fake_server()})
    assert isinstance(client, ToolClient)
    tools = asyncio.run(client.list_tools())
    assert [(tool.server, tool.name, tool.read_only) for tool in tools] == [
        ("moodle", "get_submissions", True)
    ]


def test_client_passes_only_accepted_arguments():
    client = McpToolClient({"moodle": fake_server()})
    answer = asyncio.run(
        client.call_tool("moodle", "get_submissions", {**CONFIG, "event": {}}, read_only=True)
    )
    assert answer["outcome"] == "ok"
    assert len(answer["works"]) == 3


def test_client_refuses_tool_with_effects_for_read_only_call():
    client = McpToolClient({"moodle": writer_server()})
    with pytest.raises(ToolCallError, match="меняет внешнюю систему"):
        asyncio.run(client.call_tool("moodle", "get_submissions", CONFIG, read_only=True))
    # Агенту через `context.tools` доступно только чтение.
    with pytest.raises(ToolCallError, match="меняет внешнюю систему"):
        asyncio.run(client.call("moodle", "get_submissions", CONFIG))


def test_client_refuses_not_allowed_or_unknown_tool():
    client = McpToolClient({"moodle": fake_server()}, allowed={("moodle", "other")})
    with pytest.raises(ToolCallError, match="не разрешён"):
        asyncio.run(client.call("moodle", "get_submissions", CONFIG))
    assert asyncio.run(client.list_tools()) == []
    with pytest.raises(ToolCallError, match="нет инструмента"):
        asyncio.run(
            McpToolClient({"moodle": fake_server()}).call_tool(
                "moodle", "delete_course", {}, read_only=True
            )
        )


def test_server_error_text_reaches_teacher_without_sdk_prefix():
    client = McpToolClient({"moodle": fake_server(FakeMoodle(token="f" * 32))})
    with pytest.raises(ToolCallError) as error:
        asyncio.run(client.call_tool("moodle", "get_submissions", CONFIG, read_only=True))
    assert (
        str(error.value)
        == "MCP-сервер «moodle»: Moodle не принял токен: проверь токен в подключении"
    )


def test_builtin_server_gets_credentials_only_through_its_environment():
    params = builtin_server("moodle", url="http://moodle.test", token=TOKEN)
    assert params.args == ["-m", "mcp_servers.moodle"]
    assert params.env == {"MOODLE_URL": "http://moodle.test", "MOODLE_TOKEN": TOKEN}
    with pytest.raises(ToolCallError, match="неизвестный MCP-сервер"):
        builtin_server("gmail", url="x", token="y")


def test_moodle_block_saves_works_and_passes_file_refs():
    seen = []
    registry = registry_with(fake_server(), seen)
    assert registry.problems == []
    block = registry.blocks["source.moodle_submissions"]
    store = FakeStore()

    result = asyncio.run(block.run({"event": None}, CONFIG, context(store)))

    assert isinstance(result, Done) and result.outcome == "ok"
    assert [owner.int for owner, _ in seen] == [1] and seen[0][1] == "moodle"
    works = [FileRef.model_validate(item) for item in result.outputs["works"]]
    assert [(w.name, w.kind) for w in works] == [
        ("work1.pdf", "document"),
        ("work2.docx", "document"),
        ("solution.py", "code"),
    ]
    assert works[0].meta["moodle_user_id"] == 4
    assert works[0].student_id is None
    # Файлы лежат в хранилище преподавателя, содержимое совпадает с присланным Moodle.
    assert asyncio.run(store.read_file(works[2].id)) == FILES["3/solution.py"]
    assert "content_base64" not in str(result.outputs)

    again = asyncio.run(block.run({"event": None}, CONFIG, context(store)))
    assert [item["id"] for item in again.outputs["works"]] == [w.id for w in works]


def test_no_works_is_empty_outcome():
    moodle = FakeMoodle([make_submission(4, 7, "draft", [])])
    block = registry_with(fake_server(moodle)).blocks["source.moodle_submissions"]
    result = asyncio.run(block.run({}, CONFIG, context(FakeStore())))
    assert result == Done(outcome="empty", outputs={"works": []})


def test_block_without_effects_refuses_tool_with_effects():
    block = registry_with(writer_server()).blocks["source.moodle_submissions"]
    with pytest.raises(RuntimeError, match="меняет внешнюю систему"):
        asyncio.run(block.run({}, CONFIG, context(FakeStore())))


def test_block_needs_teacher_of_the_run():
    block = registry_with(fake_server()).blocks["source.moodle_submissions"]
    with pytest.raises(RuntimeError, match="нужен преподаватель"):
        asyncio.run(block.run({}, CONFIG, context(FakeStore(), teacher=None)))


@pytest.mark.parametrize(
    ("answer", "match"),
    [
        ({"works": [], "outcome": "lost"}, "неизвестный исход"),
        ({"works": [], "grades": [], "outcome": "ok"}, "нет среди выходов"),
        ({"works": [{"name": "a.pdf"}], "outcome": "ok"}, "без содержимого"),
        ({"works": [{"name": "a.pdf", "content_base64": "@@"}], "outcome": "ok"}, "неверном"),
        (
            {
                "works": [
                    {"name": "a.pdf", "content_base64": base64.b64encode(b"x" * (10 * 2**20 + 1))}
                ],
                "outcome": "ok",
            },
            "больше 10 МиБ",
        ),
    ],
)
def test_bad_server_answer_is_block_error(answer, match):
    server = MCPServer("moodle")
    answer = {
        **answer,
        "works": [
            {**w, "content_base64": w["content_base64"].decode()}
            if isinstance(w.get("content_base64"), bytes)
            else w
            for w in answer["works"]
        ],
    }

    @server.tool(name="get_submissions", annotations=ToolAnnotations(read_only_hint=True))
    async def get_submissions(course_id: int, assignment_id: int) -> dict[str, Any]:
        return answer

    block = registry_with(server).blocks["source.moodle_submissions"]
    with pytest.raises(RuntimeError, match=match):
        asyncio.run(block.run({}, CONFIG, context(FakeStore())))


def test_unknown_server_is_not_loaded(tmp_path):
    folder = tmp_path / "blocks" / "x"
    folder.mkdir(parents=True)
    (folder / "block.yaml").write_text(
        "id: source.gmail\nversion: 0.1.0\nname: Почта\ndescription: Почта\nauthor: test\n"
        "category: source\nruntime: {type: mcp, server: gmail, tool: read}\n",
        encoding="utf-8",
    )

    async def tools_for(owner_id, name):
        raise AssertionError("не должен вызываться")

    registry = load_registry(tmp_path / "blocks", {"mcp": mcp_connector(tools_for)})
    assert "неизвестный MCP-сервер «gmail»" in str(registry.problems)
