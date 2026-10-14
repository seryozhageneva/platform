"""Репозиторий работ учеников (ADR 0016).

Работу ученика из урока записывает слой сборки, когда блок, который ждал ученика, принял
его ответ (`backend/triggers/assembly.py`). Блок о базе не знает: у него хранилище платформы
только на чтение (ADR 0014). Читает работы преподаватель — всегда в пределах своих.
"""

import uuid

from sqlalchemy import select

from backend.core.contracts.ports import Answer
from backend.models.db import Sessions
from backend.models.tables import SubmissionRow, SubmissionSource


class SubmissionRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def add_answer(
        self,
        owner_id: uuid.UUID,
        answer: Answer,
        *,
        run_id: uuid.UUID,
        node_id: str,
        student_id: uuid.UUID | None = None,
    ) -> SubmissionRow:
        """Записывает принятый ответ ученика в уроке на платформе."""
        row = SubmissionRow(
            owner_id=owner_id,
            student_id=student_id,
            run_id=run_id,
            node_id=node_id,
            task_id=answer.task_id,
            source=SubmissionSource.PLATFORM,
            form=answer.form,
            text=answer.text,
            file=None if answer.file is None else answer.file.model_dump(mode="json"),
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def for_run(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> list[SubmissionRow]:
        """Работы одного запуска этого преподавателя в том порядке, в каком они сданы."""
        query = (
            select(SubmissionRow)
            .where(SubmissionRow.owner_id == owner_id, SubmissionRow.run_id == run_id)
            .order_by(SubmissionRow.created_at)
        )
        async with self._sessions() as session:
            return list(await session.scalars(query))
