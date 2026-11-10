"""Ручная проверка API: пайплайн и журнал (задача 08), банк задач (задача 09), ответ на
паузе (задача 10).

Сначала в одном терминале поднимается сервер:  uv run python -m backend.api
Один раз заведи demo.teacher@example.test командой backend.api.create_teacher.
Затем в другом терминале запусти проверку:           uv run python -m experiments.api_check

Это не тест: скрипт пишет в рабочую базу выдуманные задачи, пайплайны и запуски. Первый
пайплайн — триггер и развилка «каким способом запущен». Второй — триггер и блок
«Источник: банк задач», который берёт задачу
нужной темы и сложности; третий — урок из двух задач: «взять задачу» и «показать задачу и
принять ответ». Скрипт отвечает за ученика выдуманными ответами, и запуск после каждого
ответа идёт дальше. Ответы записываются в работы учеников. Модель не вызывается.
"""

import sys
from getpass import getpass
from typing import Any

import httpx

SERVER = "http://127.0.0.1:8000/api/v1"
DEMO_EMAIL = "demo.teacher@example.test"
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

LESSON_PIPELINE: dict[str, Any] = {
    "format": 1,
    "id": "api_check_lesson",
    "name": "Проверка ответа на паузе",
    "params": [{"name": "topic", "title": "Тема", "type": "string"}],
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "take_task",
            "type": "block",
            "block": "source.task_bank",
            "title": "Взять задачу",
            "config": {"topic": {"$param": "topic"}, "difficulty": 1},
            "inputs": {"previous": "take_task.task"},
            "limit": {"max": 2},
        },
        {
            "id": "show",
            "type": "block",
            "block": "student.show_task",
            "title": "Показать задачу и принять ответ",
            "inputs": {"task": "take_task.task"},
        },
    ],
    "transitions": [
        {"from": "start", "to": "take_task"},
        {"from": "take_task", "when": "ok", "to": "show"},
        {"from": "show", "when": "answer", "to": "take_task"},
    ],
}


def check(response: httpx.Response) -> Any:
    if response.is_error:
        raise SystemExit(f"Сервер ответил отказом {response.status_code}: {response.text}")
    return response.json()


def main() -> int:
    with httpx.Client(base_url=SERVER, headers={"Origin": "http://127.0.0.1:8000"}) as api:
        try:
            api.get("/health")
        except httpx.ConnectError:
            print("Сервер не отвечает. Подними его: uv run python -m backend.api")
            return 1
        user = check(
            api.post(
                "/auth/teacher",
                json={"email": DEMO_EMAIL, "password": getpass("Пароль демо-преподавателя: ")},
            )
        )
        print(f"Преподаватель: {user['name']}")
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
        check_answer(api)
        api.post("/auth/logout").raise_for_status()
    print("Готово: запуск встаёт на паузу и продолжается после ответа.")
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


def check_answer(api: httpx.Client) -> None:
    pipeline = check(api.post("/pipelines", json=LESSON_PIPELINE))
    run = check(
        api.post(f"/pipelines/{pipeline['id']}/runs", json={"params": {"topic": DEMO_TOPIC}})
    )
    print(f"6. Урок из двух задач запущен: {run['id']}")
    number = 0
    while run["status"] == "waiting":
        number += 1
        [waiting] = run["waiting"]
        screen = waiting["data"]
        print(f"   запуск ждёт ответа на узле {waiting['node_id']}: {screen['statement']}")
        body = {
            "node_id": waiting["node_id"],
            "response": {
                "action": "answer",
                "answer": {
                    "task_id": screen["task_id"],
                    "form": "text",
                    "text": f"демо-ответ {number}",
                },
            },
        }
        run = check(api.post(f"/runs/{run['id']}/responses", json=body))
        print(f"   ответ {number} принят, статус запуска «{run['status']}»")
    if run["status"] != "done" or number != 2:
        raise SystemExit(f"Ожидались два ответа и конец урока, а запуск: {run}")
    steps = [event["type"] for event in check(api.get(f"/runs/{run['id']}/events"))]
    paused, resumed = steps.count("node_waiting"), steps.count("node_resumed")
    print(f"   в журнале пауз: {paused}, продолжений: {resumed}")


if __name__ == "__main__":
    sys.exit(main())
