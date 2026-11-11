"""MCP-сервер Moodle: инструменты чтения работ (задача 23, ADR 0028).

Платформа запускает сервер дочерней программой (`python -m mcp_servers.moodle`) и говорит
с ним по stdin/stdout. Адрес сайта и токен берутся из переменных окружения `MOODLE_URL` и
`MOODLE_TOKEN`, которые ставит платформа из подключения преподавателя.

Ответ инструмента — поля с именами выходов блока и поле `outcome` (docs/contract.md,
раздел 2). Файл передаётся содержимым в base64: сервер не знает хранилища платформы, а
сохраняет файл и выдаёт ссылку `File` уже платформа.
"""

import base64
import logging
from collections.abc import Callable
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.moodle.moodle_api import MoodleApi, MoodleError

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


class WorkFile(BaseModel):
    """Файл сданной работы. Имени студента нет — только его номер в Moodle в `meta`."""

    name: str
    kind: Literal["document", "code", "image", "other"]
    media_type: str
    size: int
    content_base64: str
    meta: dict[str, Any] = {}


class Submissions(BaseModel):
    works: list[WorkFile] = Field(description="Файлы сданных работ; черновиков здесь нет")
    outcome: Literal["ok", "empty"]


def build_server(make_api: Callable[[], MoodleApi]) -> MCPServer:
    """Сервер с инструментами; `make_api` даёт клиента Moodle на один вызов."""
    server = MCPServer(
        "moodle",
        instructions="Чтение сданных работ из Moodle. Ничего в Moodle не меняет.",
    )

    @server.tool(
        name="get_submissions",
        title="Сданные работы задания",
        description=(
            "Файлы работ, сданных по заданию курса Moodle. Черновики не берутся. "
            "Исход empty — сданных работ нет."
        ),
        annotations=READ_ONLY,
    )
    async def get_submissions(course_id: int, assignment_id: int) -> Submissions:
        try:
            files = await make_api().submitted_files(course_id, assignment_id)
        except MoodleError as error:
            raise ToolError(str(error)) from None
        works = [
            WorkFile(
                name=file.name,
                kind=file.kind,  # type: ignore[arg-type]
                media_type=file.media_type,
                size=len(file.content),
                content_base64=base64.b64encode(file.content).decode("ascii"),
                meta=file.meta,
            )
            for file in files
        ]
        return Submissions(works=works, outcome="ok" if works else "empty")

    return server


def quiet_http_logs() -> None:
    """httpx пишет в журнал адрес каждого запроса, а в адресе файла Moodle — токен."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def server_from_env(environ: dict[str, str]) -> MCPServer:
    url = environ.get("MOODLE_URL", "")
    token = environ.get("MOODLE_TOKEN", "")
    # Один клиент на процесс: процесс живёт ровно столько, сколько нужно платформе.
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False)

    def make_api() -> MoodleApi:
        try:
            return MoodleApi(url, token, client)
        except MoodleError as error:
            raise ToolError(str(error)) from None

    return build_server(make_api)
