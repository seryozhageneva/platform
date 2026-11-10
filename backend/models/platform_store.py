"""Хранилище платформы на базе: интерфейс `PlatformStore` из контракта (ADR 0014, ADR 0023).

Хранилище создаётся для одного преподавателя — того, чей запуск идёт. Блок, который его
получил, не называет преподавателя и чужих задач и файлов не видит. Отдаются только
подтверждённые задачи: черновик в урок не попадает.
"""

import uuid

from backend.core.contracts.ports import FileRef, Task
from backend.models import files as file_rows
from backend.models.files import FileRepository
from backend.models.tables import TaskStatus
from backend.models.tasks import TaskRepository, as_contract


def _key(value: str) -> uuid.UUID | None:
    """Номер, который не похож на номер в базе, — это «нет такого», а не ошибка."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class PgPlatformStore:
    def __init__(self, tasks: TaskRepository, files: FileRepository, owner_id: uuid.UUID) -> None:
        self._tasks = tasks
        self._files = files
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
        key = _key(task_id)
        if key is None:
            return None
        row = await self._tasks.get(self._owner_id, key)
        if row is None or row.status != TaskStatus.APPROVED:
            return None
        return as_contract(row)

    async def get_file(self, file_id: str) -> FileRef | None:
        key = _key(file_id)
        if key is None:
            return None
        row = await self._files.get(self._owner_id, key)
        return None if row is None else file_rows.as_contract(row)

    async def read_file(self, file_id: str) -> bytes | None:
        key = _key(file_id)
        if key is None:
            return None
        return await self._files.read(self._owner_id, key)
