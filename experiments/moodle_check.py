"""Ручная проверка MCP-сервера Moodle на тестовом Moodle (задача 23, ADR 0028).

Сначала подними и наполни тестовый Moodle:
    docker compose -f docker-compose.moodle.yml up -d --wait
    uv run python -m experiments.moodle_setup
Затем:
    uv run python -m experiments.moodle_check

Скрипт запускает MCP-сервер Moodle дочерней программой — так же, как это делает платформа, —
спрашивает у него список инструментов и сданные работы задания и печатает, что пришло.
Токен на экран не выводится. Это не тест: база платформы не нужна и не затрагивается.
"""

import asyncio
import base64

from backend.mcp_client.client import McpToolClient, builtin_server
from experiments.moodle_setup import seed_test_moodle


async def check() -> None:
    moodle = seed_test_moodle()
    print(f"Тестовый Moodle: {moodle.url}, курс {moodle.course_id}, задание {moodle.assignment_id}")
    client = McpToolClient({"moodle": builtin_server("moodle", url=moodle.url, token=moodle.token)})
    for tool in await client.list_tools():
        mark = "только чтение" if tool.read_only else "МЕНЯЕТ ВНЕШНЮЮ СИСТЕМУ"
        print(f"Инструмент {tool.server}.{tool.name}: {mark}")
    answer = await client.call_tool(
        "moodle",
        "get_submissions",
        {"course_id": moodle.course_id, "assignment_id": moodle.assignment_id},
        read_only=True,
    )
    print(f"Исход: {answer['outcome']}, работ: {len(answer['works'])}")
    for work in answer["works"]:
        size = len(base64.b64decode(work["content_base64"]))
        print(
            f"  студент Moodle №{work['meta']['moodle_user_id']}: {work['name']} "
            f"({work['kind']}, {work['media_type']}, {size} байт)"
        )


if __name__ == "__main__":
    asyncio.run(check())
