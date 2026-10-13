"""Ручная проверка API: сохранить пайплайн запросом, запустить запросом, прочитать журнал.

Сначала в одном терминале поднимается сервер:  uv run python -m backend.api
Потом в другом запускается проверка:           uv run python -m experiments.api_check

Это не тест: скрипт пишет в рабочую базу выдуманного преподавателя (почта на `example.test`),
пайплайн и запуск. Настоящих блоков в платформе ещё нет, поэтому пайплайн состоит из
триггера и развилки «каким способом запущен». Модель не вызывается.
"""

import asyncio
import sys
from typing import Any

import httpx

from backend.models.db import make_engine, make_sessions
from backend.models.users import UserRepository

SERVER = "http://127.0.0.1:8000/api/v1"
TEACHER = {"name": "Демо-преподаватель", "email": "demo.teacher@example.test"}
PIPELINE: dict[str, Any] = {
    "format": 1,
    "id": "api_check",
    "name": "Проверка API",
    "nodes": [
        {
            "id": "start",
            "type": "trigger",
            "title": "Преподаватель нажал «Запустить»",
            "launches": [{"type": "manual"}],
        },
        {
            "id": "how",
            "type": "switch",
            "title": "Каким способом запущен",
            "value": "start.event",
            "field": "trigger",
        },
    ],
    "transitions": [{"from": "start", "to": "how"}],
}


async def demo_teacher_id() -> str:
    """Выдуманный преподаватель в рабочей базе; создаётся один раз."""
    engine = make_engine()
    try:
        users = UserRepository(make_sessions(engine))
        teacher = await users.find_by_email(TEACHER["email"])
        if teacher is None:
            teacher = await users.create_teacher(**TEACHER)
        return str(teacher.id)
    finally:
        await engine.dispose()


def check(response: httpx.Response) -> Any:
    if response.is_error:
        raise SystemExit(f"Сервер ответил отказом {response.status_code}: {response.text}")
    return response.json()


def main() -> int:
    teacher_id = asyncio.run(demo_teacher_id())
    print(f"Преподаватель: {TEACHER['name']} ({teacher_id})")
    with httpx.Client(base_url=SERVER, headers={"X-Teacher-Id": teacher_id}) as api:
        try:
            api.get("/health")
        except httpx.ConnectError:
            print("Сервер не отвечает. Подними его: uv run python -m backend.api")
            return 1
        pipeline = check(api.post("/pipelines", json=PIPELINE))
        print(f"1. Пайплайн сохранён: {pipeline['id']}, версия {pipeline['version']}")
        run = check(api.post(f"/pipelines/{pipeline['id']}/runs"))
        print(f"2. Запуск создан запросом: {run['id']}, статус «{run['status']}»")
        print("3. Журнал событий запуска:")
        for event in check(api.get(f"/runs/{run['id']}/events")):
            print(f"   узел «{event['node_id']}»: {event['type']} {event['data'] or ''}")
    print("Готово: пайплайн запускается запросом, события видны в журнале.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
