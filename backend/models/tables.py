"""Таблицы базы данных (ADR 0007).

Десять таблиц: люди, группы и их состав, банк задач, пайплайны и их версии, назначения,
запуски, журнал событий и журнал вызовов модели (ADR 0012). Остальные сущности из
docs/vision.md добавляются миграциями в задачах, где они впервые нужны. После правки этого
файла нужна новая миграция: тест `tests/models/test_migrations.py` падает, если забыли
таблицу, столбец или индекс. Изменение допустимых значений (`CHECK`) он не видит — их
проверяют тесты, которые сохраняют каждое значение перечисления.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.contracts.ports import CheckMethod
from backend.core.contracts.state import RunStatus


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class GroupSource(StrEnum):
    PLATFORM = "platform"
    MOODLE = "moodle"


class TaskStatus(StrEnum):
    """В урок попадают только подтверждённые задачи."""

    DRAFT = "draft"
    APPROVED = "approved"


def _one_of(column: str, values: type[StrEnum]) -> CheckConstraint:
    """Столбец принимает только значения перечисления — за этим следит сама база."""
    allowed = ", ".join(f"'{item.value}'" for item in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_allowed")


EMPTY_JSON = text("'{}'::jsonb")


class Base(DeclarativeBase):
    # Имена ограничений строятся по одному правилу, чтобы миграции могли на них ссылаться.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        str: Text,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


class UserRow(Base):
    """Человек: администратор, преподаватель или ученик.

    Об ученике хранится минимум: имя или псевдоним. У ученика есть владелец — преподаватель,
    который его добавил. Как выдаётся и отзывается личная ссылка — задача 13.
    """

    __tablename__ = "users"
    __table_args__ = (
        _one_of("role", Role),
        CheckConstraint("role <> 'student' OR owner_id IS NOT NULL", name="student_has_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(20))
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(unique=True)
    password_hash: Mapped[str | None]
    link_token_hash: Mapped[str | None] = mapped_column(unique=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    # Идентификаторы во внешних системах, например в Moodle.
    external_ids: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GroupRow(Base):
    __tablename__ = "groups"
    __table_args__ = (_one_of("source", GroupSource),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str]
    source: Mapped[str] = mapped_column(String(20), default=GroupSource.PLATFORM)
    # Для группы из Moodle — идентификатор курса.
    external_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


group_members = Table(
    "group_members",
    Base.metadata,
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("student_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class TaskRow(Base):
    """Задача банка. Поля совпадают с типом `Task` из контракта, плюс владелец и статус."""

    __tablename__ = "tasks"
    __table_args__ = (
        _one_of("check_method", CheckMethod),
        _one_of("status", TaskStatus),
        CheckConstraint("difficulty >= 1", name="difficulty_positive"),
        Index("ix_tasks_search", "owner_id", "subject", "topic", "difficulty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str]
    topic: Mapped[str]
    difficulty: Mapped[int]
    statement: Mapped[str]
    check_method: Mapped[str] = mapped_column(String(20))
    answer: Mapped[str | None]
    solution: Mapped[str | None]
    tests: Mapped[str | None]
    rubric: Mapped[str | None]
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PipelineRow(Base):
    """Пайплайн: кому принадлежит и какая версия последняя. Сам граф — в `pipeline_versions`.

    `slug` — читаемое имя из поля `id` файла пайплайна. Ключом в базе оно не служит: у двух
    преподавателей оно может совпасть.
    """

    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str]
    name: Mapped[str]
    latest_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PipelineVersionRow(Base):
    """Одна сохранённая версия графа. Версии не меняются: запуск ссылается на свою."""

    __tablename__ = "pipeline_versions"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    graph: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AssignmentRow(Base):
    """Назначение: пайплайн с такими значениями параметров — ученику или группе."""

    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("(student_id IS NULL) <> (group_id IS NULL)", name="one_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id"))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    due_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RunRow(Base):
    """Запуск. По столбцам ищет кабинет; всё остальное состояние движка лежит в `state`."""

    __tablename__ = "runs"
    __table_args__ = (
        _one_of("status", RunStatus),
        ForeignKeyConstraint(
            ["pipeline_id", "pipeline_version"],
            ["pipeline_versions.pipeline_id", "pipeline_versions.version"],
            name="fk_runs_pipeline_version",
        ),
        # Один запуск на ученика и назначение: повторное открытие урока его продолжает.
        Index(
            "uq_runs_assignment_student",
            "assignment_id",
            "student_id",
            unique=True,
            postgresql_where=text("assignment_id IS NOT NULL"),
        ),
        Index("ix_runs_teacher_status", "teacher_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID]
    pipeline_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignments.id"))
    error: Mapped[str | None]
    state: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class EventRow(Base):
    """Запись журнала событий. Номер растёт сам, поэтому порядок событий не теряется."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_run", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_id: Mapped[str]
    type: Mapped[str]
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LLMCallRow(Base):
    """Запись журнала вызовов модели (ADR 0012): только цифры, без текста запроса и ответа.

    Запуск и узел пусты у вызова вне запуска — например, у ручной проверки модели.
    `error` — короткое обозначение причины неудачи; у удачного вызова пусто.
    """

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_not_negative"),
        CheckConstraint("latency_ms >= 0", name="latency_not_negative"),
        Index("ix_llm_calls_run", "run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_id: Mapped[str | None]
    provider: Mapped[str]
    model: Mapped[str]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    latency_ms: Mapped[int]
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
