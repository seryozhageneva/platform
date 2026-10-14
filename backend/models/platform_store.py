"""Хранилище платформы на базе: интерфейс `PlatformStore` из контракта (ADR 0014).

Хранилище создаётся для одного преподавателя — того, чей запуск идёт. Блок, который его
получил, не называет преподавателя и чужих задач не видит. Отдаются только подтверждённые
задачи: черновик в урок не попадает.
"""

import uuid

from backend.core.contracts.ports import Task
from backend.models.tables import TaskStatus
from backend.models.tasks import TaskRepository, as_contract


class PgPlatformStore:
    def __init__(self, tasks: TaskRepository, owner_id: uuid.UUID) -> None:
        self._tasks = tasks
        self._owner_id = owner_id

    async def find_tasks(
        self,
        *,
        topic: str | None = None,
        difficulty: int | None = None,
        subject: str | None = None,
    ) -> list[Task]:
        rows = await self._tasks.find(
            self._owner_id, subject=subject, topic=topic, difficulty=difficulty
        )
        return [as_contract(row) for row in rows]

    async def get_task(self, task_id: str) -> Task | None:
        # Номер, который не похож на номер задачи в базе, — это «нет такой», а не ошибка.
        try:
            key = uuid.UUID(task_id)
        except ValueError:
            return None
        row = await self._tasks.get(self._owner_id, key)
        if row is None or row.status != TaskStatus.APPROVED:
            return None
        return as_contract(row)
