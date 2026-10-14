"""Ручная проверка API: пайплайн и журнал (задача 08), банк задач (задача 09).

Сначала в одном терминале поднимается сервер:  uv run python -m backend.api
Потом в другом запускается проверка:           uv run python -m experiments.api_check

Это не тест: скрипт пишет в рабочую базу выдуманного преподавателя (почта на `example.test`),
его выдуманные задачи, пайплайны и запуски. Первый пайплайн — триггер и развилка «каким
способом запущен»; второй — триггер и блок «Источник: банк задач», который берёт задачу
нужной темы и сложности. Модель не вызывается.
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

# Выдуманные задачи демо-преподавателя; создаются один раз.
DEMO_TOPIC = "демо: логарифмы"
TASKS: list[dict[str, Any]] = [
    {"difficulty": 1, "statement": "Вычислите $\\log_2 8$.", "answer": "3"},
    {"difficulty": 2, "statement": "Решите $\\log_3 x = 4$.", "answer": "81"},
    {"difficulty": 3, "statement": "Решите $\\log_2 (x+1) + \\log_2 (x-1) = 3$.", "answer": "3"},
]
BANK_PIPELINE: dict[str, Any] = {
    "format": 1,
    "id": "api_check_bank",
    "name": "Проверка банка задач",
    "params": [
        {"name": "topic", "title": "Тема", "type": "string"},
        {"name": "difficulty", "title": "Сложность", "type": "integer", "default": 1},
    ],
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "take_task",
            "type": "block",
            "block": "source.task_bank",
            "title": "Взять задачу",
            "config": {"topic": {"$param": "topic"}, "difficulty": {"$param": "difficulty"}},
        },
    ],
    "transitions": [{"from": "start", "to": "take_task"}],
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
        check_bank(api)
    print("Готово: задачи создаются и выбираются по теме и сложности.")
    return 0


def check_bank(api: httpx.Client) -> None:
    tasks = check(api.get("/tasks", params={"topic": DEMO_TOPIC}))
    if not tasks:
        for task in TASKS:
            body = {"subject": "math", "topic": DEMO_TOPIC, "check_method": "short_answer", **task}
            tasks.append(check(api.post("/tasks", json=body)))
    print(f"4. В банке задачи темы «{DEMO_TOPIC}»:")
    for task in tasks:
        print(f"   сложность {task['difficulty']}: {task['statement']} ({task['id']})")
    pipeline = check(api.post("/pipelines", json=BANK_PIPELINE))
    params = {"topic": DEMO_TOPIC, "difficulty": 2}
    run = check(api.post(f"/pipelines/{pipeline['id']}/runs", json={"params": params}))
    print(f"5. Запуск «взять задачу» с темой и сложностью 2: статус «{run['status']}»")
    events = check(api.get(f"/runs/{run['id']}/events"))
    chosen = [event["data"] for event in events if event["type"] == "task_chosen"]
    if not chosen:
        raise SystemExit(f"Блок не выбрал задачу. Журнал: {events}")
    task = next(task for task in tasks if task["id"] == chosen[0]["task_id"])
    print(f"   блок выбрал задачу сложности {task['difficulty']}: {task['statement']}")


if __name__ == "__main__":
    sys.exit(main())
