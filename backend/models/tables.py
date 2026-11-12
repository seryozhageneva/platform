"""Таблицы базы данных (ADR 0007).

Таблицы: люди, группы и их состав, банк задач, пайплайны и их версии, назначения,
запуски, журнал событий, журнал вызовов модели (ADR 0012), работы учеников (ADR 0016),
файлы (ADR 0023), результаты кабинета (ADR 0026), подключения к внешним системам (ADR 0028),
расписания (ADR 0032) и наблюдение за Moodle с обработанными сдачами (ADR 0034).
Остальные сущности из
docs/vision.md добавляются миграциями в задачах, где они впервые нужны. После правки этого
файла нужна новая миграция: тест `tests/models/test_migrations.py` падает, если забыли
таблицу, столбец или индекс. Изменение допустимых значений (`CHECK`) он не видит — их
проверяют тесты, которые сохраняют каждое значение перечисления.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.contracts.ports import AnswerForm, CheckMethod, FileKind
from backend.core.contracts.state import RunStatus


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class GroupSource(StrEnum):
    PLATFORM = "platform"
    MOODLE = "moodle"


class ConnectionKind(StrEnum):
    """К какой внешней системе подключается преподаватель."""

    MOODLE = "moodle"
    TELEGRAM = "telegram"
    CLOUD = "cloud"


class TaskStatus(StrEnum):
    """В урок попадают только подтверждённые задачи."""

    DRAFT = "draft"
    APPROVED = "approved"


class SubmissionSource(StrEnum):
    """Откуда работа: ответ в уроке на платформе или работа, сданная в Moodle (задача 23)."""

    PLATFORM = "platform"
    MOODLE = "moodle"


class VerdictStatus(StrEnum):
    """Оценку ИИ преподаватель может подтвердить или исправить (задачи 18 и 21)."""

    PRELIMINARY = "preliminary"
    CONFIRMED = "confirmed"


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
    который его добавил. Личная ссылка хранится в виде хэша с отдельным сроком действия.
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
    notification_email: Mapped[str | None]
    password_hash: Mapped[str | None]
    link_token_hash: Mapped[str | None] = mapped_column(unique=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    # Идентификаторы во внешних системах, например в Moodle.
    external_ids: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LoginSessionRow(Base):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class ScheduleRow(Base):
    """Настройки запуска и последняя поставленная в очередь минута."""

    __tablename__ = "schedules"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    last_fired_at: Mapped[datetime | None]


class MoodleWatchRow(Base):
    """Запуск по событию Moodle: включён ли опрос, параметры и последний опрос (ADR 0034)."""

    __tablename__ = "moodle_watches"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSON)
    last_polled_at: Mapped[datetime | None]
    # Текст последней ошибки опроса для преподавателя; пусто — опрос прошёл.
    last_error: Mapped[str | None] = mapped_column(Text)


class MoodleSeenRow(Base):
    """Сдача Moodle, для которой уже создан запуск. Изменённая сдача — новая строка."""

    __tablename__ = "moodle_seen_submissions"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True
    )
    submission_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Время сдачи из Moodle (Unix-время): после доработки оно меняется.
    submitted_at: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


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


class ApprovalRow(Base):
    """Снимок одной паузы и решение преподавателя по нему."""

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_run_id", "run_id"),
        Index(
            "uq_approvals_open_run",
            "run_id",
            unique=True,
            postgresql_where=text("answered_at IS NULL"),
        ),
        CheckConstraint(
            "(answered_at IS NULL AND outcome IS NULL AND response IS NULL) OR "
            "(answered_at IS NOT NULL AND outcome IS NOT NULL "
            "AND outcome IN ('approved', 'rejected') AND response IS NOT NULL)",
            name="decision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_id: Mapped[str]
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    snapshot: Mapped[dict[str, Any]]
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    outcome: Mapped[str | None]
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    answered_at: Mapped[datetime | None]


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


class SubmissionRow(Base):
    """Работа ученика (ADR 0016): принятый ответ в уроке или работа, сданная в Moodle.

    Ученик пуст у пробного запуска преподавателя: у запуска «вручную» ученика нет. Номер
    задачи — строка без связи с банком: у задания Moodle номер не из нашей базы. Файл не
    хранится в базе — только ссылка на него (тип `File` из контракта). Оценка, комментарий
    и статус вердикта пусты, пока работу не проверили (задачи 11 и 21, ADR 0031).
    """

    __tablename__ = "submissions"
    __table_args__ = (
        _one_of("source", SubmissionSource),
        _one_of("form", AnswerForm),
        _one_of("verdict_status", VerdictStatus),
        Index("ix_submissions_run", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    node_id: Mapped[str | None]
    task_id: Mapped[str | None]
    source: Mapped[str] = mapped_column(String(20))
    form: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str | None]
    # Нет файла — пустое значение базы, а не JSON `null`: так работает поиск `file IS NULL`.
    file: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # Верно ли решена работа — поле `correct` вердикта (ADR 0031); пусто, пока не проверили.
    correct: Mapped[bool | None]
    score: Mapped[float | None]
    max_score: Mapped[float | None]
    comment: Mapped[str | None]
    verdict_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class FileRow(Base):
    """Загруженный файл платформы (ADR 0023): описание — как у типа `File`, плюс содержимое.

    Файл принадлежит преподавателю: он загрузил его сам, или это работа его ученика. Номер
    строки — поле `id` у ссылки `File` в пайплайне. Содержимое лежит прямо в базе и читается
    только по отдельной просьбе: описание файла его не тянет. Размер всегда совпадает с
    длиной содержимого — за этим следит база.
    """

    __tablename__ = "files"
    __table_args__ = (
        _one_of("kind", FileKind),
        CheckConstraint("size = octet_length(content)", name="size_matches_content"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(String(20))
    media_type: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CabinetResultRow(Base):
    """Результат запуска для преподавателя или конкретного ученика (ADR 0026)."""

    __tablename__ = "cabinet_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    node_id: Mapped[str]
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str]
    content: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ConnectionRow(Base):
    """Подключение преподавателя к внешней системе (ADR 0028): адрес и зашифрованный токен.

    У преподавателя одно подключение каждого вида: блок называет только вид («moodle»), а
    какой сайт и чей токен — решает подключение того, чей запуск идёт. Токен хранится только
    зашифрованным ключом из `.env` (`PLATFORM_SECRET_KEY`); открытым текстом его в базе нет.
    """

    __tablename__ = "connections"
    __table_args__ = (
        _one_of("kind", ConnectionKind),
        UniqueConstraint("owner_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    url: Mapped[str]
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
