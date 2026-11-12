"""Инструменты агента внутри блока: `context.tools` (задача 28, ADR 0035).

Блок ИИ-обработки сам решает, какой инструмент вызвать. Здесь, в слое сборки, ему выдаются
только инструменты из списка `tools` его манифеста и только с подключениями преподавателя
запуска. Вызывать можно лишь инструменты, которые сам сервер пометил «только чтение»: это
проверяет MCP-клиент при каждом вызове.

Подключение берётся при первом обращении к инструментам, а не при выдаче. Так блоку, которому
преподаватель инструменты не включил, подключение Moodle и не нужно.
"""

import uuid
from typing import Any

from backend.core.contracts.interfaces import ToolInfo
from backend.core.contracts.manifest import ToolRef
from backend.mcp_client.client import McpToolClient, ToolCallError
from backend.triggers.mcp_blocks import ToolsFor


class AgentTools:
    """`ToolClient` для одного вызова блока: разрешённые инструменты преподавателя запуска."""

    def __init__(self, tools_for: ToolsFor, owner_id: uuid.UUID, refs: list[ToolRef]) -> None:
        self._tools_for = tools_for
        self._owner_id = owner_id
        self._allowed = {(ref.server, ref.tool) for ref in refs}
        self._clients: dict[str, McpToolClient] = {}

    async def _client(self, server: str) -> McpToolClient:
        if server not in self._clients:
            self._clients[server] = await self._tools_for(self._owner_id, server)
        return self._clients[server]

    async def list_tools(self) -> list[ToolInfo]:
        found: list[ToolInfo] = []
        for server in sorted({server for server, _ in self._allowed}):
            tools = await (await self._client(server)).list_tools()
            found += [tool for tool in tools if (server, tool.name) in self._allowed]
        return found

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        if (server, tool) not in self._allowed:
            raise ToolCallError(f"инструмент «{server}.{tool}» агенту этого блока не разрешён")
        return await (await self._client(server)).call(server, tool, arguments)
