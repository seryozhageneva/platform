"""Ручная проверка MCP-сервера облака на настоящем Яндекс Диске (задача 29, ADR 0036).

    uv run python -m experiments.cloud_check /Лекции/лекция.pdf

Положи на свой Диск выдуманный файл (не работы учеников). Токен OAuth Яндекс Диска скрипт
спросит сам и на экран не выведет; в файлы он не сохраняется. Как получить токен — в
docs/deploy.md, раздел «Облако: Яндекс Диск».

Скрипт запускает MCP-сервер облака дочерней программой — так же, как это делает платформа, —
спрашивает список инструментов и скачивает файл по пути. Печатается только имя, вид, тип и
размер файла. Это не тест: база платформы не нужна и не затрагивается. Идёт в сеть.
"""

import asyncio
import base64
import sys
from getpass import getpass

from backend.mcp_client.client import McpToolClient, ToolCallError, builtin_server

CLOUD_API = "https://cloud-api.yandex.net"


async def check(path: str, token: str) -> None:
    client = McpToolClient({"cloud": builtin_server("cloud", url=CLOUD_API, token=token)})
    for tool in await client.list_tools():
        mark = "только чтение" if tool.read_only else "МЕНЯЕТ ВНЕШНЮЮ СИСТЕМУ"
        print(f"Инструмент {tool.server}.{tool.name}: {mark}")
    answer = await client.call_tool("cloud", "get_file", {"path": path}, read_only=True)
    print(f"Исход: {answer['outcome']}")
    file = answer.get("file")
    if file:
        size = len(base64.b64decode(file["content_base64"]))
        print(f"  {file['name']}: вид {file['kind']}, тип {file['media_type']}, {size} байт")
        print(f"  путь на Диске: {file['meta']['cloud_path']}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Укажи путь к файлу на Диске: python -m experiments.cloud_check /Лекции/a.pdf")
    token = getpass("Токен Яндекс Диска (не отображается): ").strip()
    try:
        asyncio.run(check(sys.argv[1], token))
    except ToolCallError as error:
        sys.exit(f"Ошибка: {error}")


if __name__ == "__main__":
    main()
