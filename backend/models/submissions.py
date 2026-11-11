"""Репозиторий работ учеников (ADR 0016).

Работу ученика из урока записывает слой сборки, когда блок, который ждал ученика, принял
его ответ (`backend/triggers/assembly.py`). Блок о базе не знает: у него хранилище платформы
только на чтение (ADR 0014). Читает работы преподаватель — всегда в пределах своих.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.contracts.ports import Answer, Verdict
from backend.models.db import Sessions
from backend.models.tables import SubmissionRow, SubmissionSource, VerdictStatus


@dataclass(frozen=True)
class SubmissionGrade:
    owner_id: uuid.UUID
    run_id: uuid.UUID
    answer: Answer
    verdict: Verdict

    async def save(self, session: AsyncSession) -> None:
        """Оценка относится к последней сдаче этого ответа в текущем уроке."""
        answer = self.answer
        query = (
            select(SubmissionRow)
            .where(
                SubmissionRow.owner_id == self.owner_id,
                SubmissionRow.run_id == self.run_id,
                SubmissionRow.source == SubmissionSource.PLATFORM,
                SubmissionRow.task_id == answer.task_id,
                SubmissionRow.form == answer.form,
                SubmissionRow.text == answer.text,
                SubmissionRow.file
                == (answer.file.model_dump(mode="json") if answer.file is not None else None),
            )
            .order_by(SubmissionRow.created_at.desc(), SubmissionRow.id.desc())
            .limit(1)
            .with_for_update()
        )
        row = await session.scalar(query)
        if row is None or row.verdict_status is not None:
            return
        verdict = self.verdict
        row.correct = verdict.correct
        row.score = verdict.score
        row.max_score = verdict.max_score
        row.comment = verdict.comment
        row.verdict_status = (
            VerdictStatus.PRELIMINARY if verdict.preliminary else VerdictStatus.CONFIRMED
        )


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
        row = self.answer_row(
            owner_id, answer, run_id=run_id, node_id=node_id, student_id=student_id
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    @staticmethod
    def answer_row(
        owner_id: uuid.UUID,
        answer: Answer,
        *,
        run_id: uuid.UUID,
        node_id: str,
        student_id: uuid.UUID | None = None,
    ) -> SubmissionRow:
        return SubmissionRow(
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

    async def for_run(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> list[SubmissionRow]:
        """Работы одного запуска этого преподавателя в том порядке, в каком они сданы."""
        query = (
            select(SubmissionRow)
            .where(SubmissionRow.owner_id == owner_id, SubmissionRow.run_id == run_id)
            .order_by(SubmissionRow.created_at)
        )
        async with self._sessions() as session:
            return list(await session.scalars(query))
