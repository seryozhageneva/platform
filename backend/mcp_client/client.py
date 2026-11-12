"""MCP-клиент платформы: интерфейс `ToolClient` из контракта (ADR 0006, ADR 0028).

Клиент говорит с MCP-серверами по официальному SDK. Сервер платформы (`mcp_servers/…`)
запускается дочерней программой на один вызов: адрес внешней системы и токен он получает
через переменные окружения своего процесса и больше нигде их не видит. В тестах вместо
дочерней программы подставляется сервер в том же процессе — SDK умеет и так.

Что за инструменты у сервера и помечены ли они «только чтение», клиент спрашивает у самого
сервера при каждом вызове: так блок без последствий не вызовет инструмент с последствиями,
даже если сервер обновился.
"""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import mcp_types
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from backend.core.contracts.interfaces import ToolInfo

ROOT = Path(__file__).resolve().parents[2]
# Сколько ждать ответа инструмента: скачивание работ большого задания — не мгновенно.
TOOL_TIMEOUT = 180

# Встроенные MCP-серверы платформы: имя в манифесте → модуль, который запускается.
BUILTIN_SERVERS = {
    "moodle": "mcp_servers.moodle",
    "email": "mcp_servers.email",
    "telegram": "mcp_servers.telegram",
}

# Что сервер может получить: процесс адресуется так же, как и в тестах — по объекту сервера.
ServerTarget = Any


class ToolCallError(RuntimeError):
    """Инструмент не вызван или ответил ошибкой; текст можно показать преподавателю."""


def builtin_server(name: str, *, url: str, token: str) -> StdioServerParameters:
    """Как запустить встроенный сервер с адресом и токеном подключения."""
    if name == "telegram":
        # Telegram ходит на фиксированный адрес Bot API.
        return _stdio_server(name, env={"TELEGRAM_TOKEN": token})
    prefix = name.upper()
    return _stdio_server(name, env={f"{prefix}_URL": url, f"{prefix}_TOKEN": token})


def email_server(env: dict[str, str]) -> StdioServerParameters:
    """Почтовый сервер получает настройки ящика платформы."""
    return _stdio_server("email", env=env)


def _stdio_server(name: str, *, env: dict[str, str]) -> StdioServerParameters:
    module = BUILTIN_SERVERS.get(name)
    if module is None:
        raise ToolCallError(f"неизвестный MCP-сервер «{name}»")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env=env,
        cwd=ROOT,
    )


def tool_info(server: str, tool: mcp_types.Tool) -> ToolInfo:
    hints = tool.annotations
    return ToolInfo(
        server=server,
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(tool.input_schema or {}),
        read_only=bool(hints and hints.read_only_hint),
    )


class McpToolClient:
    """Инструменты MCP-серверов одного запуска.

    `servers` — имя сервера → как до него добраться. `allowed` — какие пары «сервер,
    инструмент» видит блок через `context.tools`; пусто — все инструменты этих серверов.
    """

    def __init__(
        self,
        servers: Mapping[str, ServerTarget],
        *,
        allowed: set[tuple[str, str]] | None = None,
        timeout: float = TOOL_TIMEOUT,
    ) -> None:
        self._servers = dict(servers)
        self._allowed = allowed
        self._timeout = timeout

    async def list_tools(self) -> list[ToolInfo]:
        found: list[ToolInfo] = []
        for server in self._servers:
            async with self._open(server) as client:
                tools = (await client.list_tools()).tools
            found += [tool_info(server, tool) for tool in tools if self._permits(server, tool.name)]
        return found

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        """Вызов для агента внутри блока: ему доступны только инструменты чтения."""
        return await self.call_tool(server, tool, arguments, read_only=True)

    async def call_tool(
        self, server: str, tool: str, arguments: Mapping[str, Any], *, read_only: bool
    ) -> Any:
        """Вызывает инструмент и возвращает его структурированный ответ.

        `read_only=True` — инструмент обязан быть помечен сервером «только чтение».
        Передаются только те значения, которые инструмент принимает по своей схеме.
        """
        if not self._permits(server, tool):
            raise ToolCallError(f"инструмент «{server}.{tool}» блоку не разрешён")
        # Отказ поднимается после выхода из сессии: внутри неё SDK завернул бы его в группу
        # исключений, и преподаватель увидел бы «не ответил» вместо причины.
        refusal: str | None = None
        result: mcp_types.CallToolResult | None = None
        try:
            async with self._open(server) as client:
                tools = {item.name: item for item in (await client.list_tools()).tools}
                info = tool_info(server, tools[tool]) if tool in tools else None
                if info is None:
                    refusal = f"у MCP-сервера «{server}» нет инструмента «{tool}»"
                elif read_only and not info.read_only:
                    refusal = (
                        f"инструмент «{server}.{tool}» меняет внешнюю систему, а блок помечен "
                        "как блок без последствий"
                    )
                else:
                    accepted = set(info.input_schema.get("properties", {}))
                    values = {name: value for name, value in arguments.items() if name in accepted}
                    result = await client.call_tool(
                        tool, values, read_timeout_seconds=self._timeout
                    )
        except Exception as error:
            # `from None`: в цепочке ошибки может оказаться описание запуска вместе с токеном.
            raise ToolCallError(
                f"MCP-сервер «{server}» не ответил ({type(error).__name__})"
            ) from None
        if refusal is not None or result is None:
            raise ToolCallError(refusal or f"MCP-сервер «{server}» ничего не ответил")
        if result.is_error:
            text = " ".join(
                block.text for block in result.content if isinstance(block, mcp_types.TextContent)
            )
            # SDK добавляет к тексту ошибки служебное начало на английском — оно лишнее.
            text = text.removeprefix(f"Error executing tool {tool}: ")
            raise ToolCallError(f"MCP-сервер «{server}»: {text or 'ошибка без текста'}")
        return result.structured_content

    def _permits(self, server: str, tool: str) -> bool:
        if server not in self._servers:
            return False
        return self._allowed is None or (server, tool) in self._allowed

    def _open(self, server: str) -> Client:
        if server not in self._servers:
            raise ToolCallError(f"MCP-сервер «{server}» блоку не подключён")
        return Client(self._servers[server], read_timeout_seconds=self._timeout)
