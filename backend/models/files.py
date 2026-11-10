"""Репозиторий загруженных файлов (ADR 0023): сохранить файл, взять описание и содержимое.

Файл принадлежит преподавателю; читать его можно только в пределах владельца. Блоки
читают файлы через хранилище платформы (`platform_store.py`), а загружает их API (задача 19).
"""

import uuid

from sqlalchemy import select

from backend.core.contracts.ports import FileKind, FileRef
from backend.models.db import Sessions
from backend.models.tables import FileRow


class FileRepository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(
        self,
        owner_id: uuid.UUID,
        *,
        name: str,
        kind: FileKind,
        media_type: str,
        content: bytes,
        student_id: uuid.UUID | None = None,
    ) -> FileRow:
        row = FileRow(
            owner_id=owner_id,
            student_id=student_id,
            name=name,
            kind=kind,
            media_type=media_type,
            size=len(content),
            content=content,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def get(self, owner_id: uuid.UUID, file_id: uuid.UUID) -> FileRow | None:
        """Описание своего файла без содержимого; `None` — такого среди своих нет."""
        query = select(FileRow).where(FileRow.id == file_id, FileRow.owner_id == owner_id)
        async with self._sessions() as session:
            return await session.scalar(query)

    async def read(self, owner_id: uuid.UUID, file_id: uuid.UUID) -> bytes | None:
        """Содержимое своего файла; `None` — такого среди своих нет."""
        query = select(FileRow.content).where(FileRow.id == file_id, FileRow.owner_id == owner_id)
        async with self._sessions() as session:
            return await session.scalar(query)


def as_contract(row: FileRow) -> FileRef:
    """Строка таблицы — в тип `File` из контракта: номер строки становится номером файла."""
    return FileRef(
        id=str(row.id),
        name=row.name,
        kind=FileKind(row.kind),
        media_type=row.media_type,
        size=row.size,
        student_id=None if row.student_id is None else str(row.student_id),
    )
