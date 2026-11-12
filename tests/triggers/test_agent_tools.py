"""Инструменты агента: только из манифеста и с подключением преподавателя (ADR 0035)."""

import asyncio
import uuid

import pytest

from backend.core.contracts.interfaces import ToolClient
from backend.core.contracts.manifest import ToolRef
from backend.mcp_client.client import McpToolClient, ToolCallError
from backend.triggers.agent_tools import AgentTools
from mcp_servers.moodle.testing import FakeMoodle, fake_server

OWNER = uuid.uuid4()
GRADES = [ToolRef(server="moodle", tool="get_course_grades")]


def make_tools(refs=GRADES, moodle=None):
    asked = []

    async def tools_for(owner_id, server):
        asked.append((owner_id, server))
        return McpToolClient({server: fake_server(moodle)})

    return AgentTools(tools_for, OWNER, refs), asked


def test_agent_sees_only_tools_of_the_manifest():
    tools, asked = make_tools()
    assert isinstance(tools, ToolClient)
    found = asyncio.run(tools.list_tools())
    assert [(tool.server, tool.name, tool.read_only) for tool in found] == [
        ("moodle", "get_course_grades", True)
    ]
    assert asked == [(OWNER, "moodle")]


def test_agent_calls_with_the_connection_of_the_run_teacher():
    moodle = FakeMoodle(max_grade=10)
    moodle.journal = {4: 8}
    tools, asked = make_tools(moodle=moodle)
    answer = asyncio.run(tools.call("moodle", "get_course_grades", {"course_id": 2}))
    assert answer["assignments"][0]["grades"] == [
        {"user_id": 4, "grade": 8.0, "graded_at": 1794393700}
    ]
    assert asked == [(OWNER, "moodle")]


def test_connection_is_not_needed_until_the_agent_uses_tools():
    tools, asked = make_tools()
    assert asked == []


@pytest.mark.parametrize("tool", ["get_submissions", "save_grade"])
def test_tool_outside_the_manifest_is_refused(tool):
    tools, asked = make_tools()
    with pytest.raises(ToolCallError, match="не разрешён"):
        asyncio.run(tools.call("moodle", tool, {"course_id": 2}))
    assert asked == []


def test_tool_with_side_effects_is_refused_even_if_listed():
    tools, _ = make_tools(refs=[ToolRef(server="moodle", tool="save_grade")])
    arguments = {"course_id": 2, "assignment_id": 1, "user_id": 4, "score": 1, "max_score": 1}
    with pytest.raises(ToolCallError, match="меняет внешнюю систему"):
        asyncio.run(tools.call("moodle", "save_grade", arguments))
