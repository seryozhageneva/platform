"""Журнал вызовов модели в PostgreSQL (ADR 0012).

Слой моделей `backend/llm/` об этом файле не знает: ему достаточно, что у журнала есть метод
`record` с такими именами аргументов. Соединяет их слой сборки. В журнале только цифры —
текст запроса и ответа сюда не попадает.
"""

import uuid

from sqlalchemy import select

from backend.models.db import Sessions
from backend.models.tables import LLMCallRow


class LLMCallRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def record(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error: str | None = None,
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        row = LLMCallRow(
            run_id=None if run_id is None else _uuid(run_id),
            node_id=node_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            error=error,
        )
        async with self._sessions.begin() as session:
            session.add(row)

    async def for_run(self, run_id: str) -> list[LLMCallRow]:
        """Вызовы одного запуска в том порядке, в каком они сделаны."""
        try:
            key = uuid.UUID(run_id)
        except ValueError:
            return []
        query = select(LLMCallRow).where(LLMCallRow.run_id == key).order_by(LLMCallRow.id)
        async with self._sessions() as session:
            return list(await session.scalars(query))


def _uuid(run_id: str) -> uuid.UUID:
    """В контракте идентификаторы — строки, в базе — UUID."""
    try:
        return uuid.UUID(run_id)
    except ValueError:
        raise ValueError(f"run_id: «{run_id}» — не идентификатор из базы (ожидался UUID)") from None
