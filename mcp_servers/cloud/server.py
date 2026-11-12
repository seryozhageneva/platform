"""MCP-сервер облака: файл с Яндекс Диска преподавателя (задача 29, ADR 0036).

Платформа запускает сервер дочерней программой (`python -m mcp_servers.cloud`) и говорит с
ним по stdin/stdout. Токен Диска сервер получает в переменной окружения `CLOUD_TOKEN` из
подключения преподавателя; адрес API Диска постоянный.

Ответ инструмента — поля с именами выходов блока и поле `outcome` (docs/contract.md,
раздел 2). Файл передаётся содержимым в base64: сохраняет его и выдаёт ссылку `File` уже
платформа.
"""

import base64
import logging
from collections.abc import Callable
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.cloud.yandex_disk import DiskError, YandexDisk

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


class CloudFile(BaseModel):
    name: str
    kind: Literal["document", "image", "other"]
    media_type: str
    size: int
    content_base64: str
    meta: dict[str, str] = Field(description="Путь к файлу на Диске: cloud_path")


class FoundFile(BaseModel):
    file: CloudFile | None = Field(default=None, description="Пусто, если файла нет")
    outcome: Literal["ok", "missing"]


def build_server(make_disk: Callable[[], YandexDisk]) -> MCPServer:
    """Сервер с инструментом; `make_disk` даёт клиента Диска на один вызов."""
    server = MCPServer("cloud", instructions="Чтение файлов с Яндекс Диска. Диск не меняется.")

    @server.tool(
        name="get_file",
        title="Файл с Яндекс Диска",
        description=(
            "Скачивает файл по пути на Яндекс Диске преподавателя, например "
            "/Лекции/лекция.pdf. Исход missing — по этому пути файла нет."
        ),
        annotations=READ_ONLY,
    )
    async def get_file(path: str) -> FoundFile:
        try:
            found = await make_disk().read(path)
        except DiskError as error:
            raise ToolError(str(error)) from None
        if found is None:
            return FoundFile(outcome="missing")
        file = CloudFile(
            name=found.name,
            kind=found.kind,  # type: ignore[arg-type]
            media_type=found.media_type,
            size=len(found.content),
            content_base64=base64.b64encode(found.content).decode("ascii"),
            meta={"cloud_path": found.path},
        )
        return FoundFile(file=file, outcome="ok")

    return server


def quiet_http_logs() -> None:
    """В журнал httpx попадают адреса запросов; ссылка скачивания подписана Диском."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def server_from_env(environ: dict[str, str]) -> MCPServer:
    token = environ.get("CLOUD_TOKEN", "")
    # Переадресации разбирает сам клиент Диска: каждая проверяется на адрес Яндекса.
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False)

    def make_disk() -> YandexDisk:
        try:
            return YandexDisk(token, client)
        except DiskError as error:
            raise ToolError(str(error)) from None

    return build_server(make_disk)
