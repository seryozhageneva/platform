"""Первая миграция: девять таблиц модели данных (ADR 0007).

Люди, группы и их состав, банк задач, пайплайны и их версии, назначения, запуски и журнал
событий. Файл создан командой `alembic revision --autogenerate` по описанию таблиц в
`backend/models/tables.py`.

Номер: 0001
Предыдущая: нет
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("link_token_hash", sa.Text(), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "external_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role <> 'student' OR owner_id IS NOT NULL", name=op.f("ck_users_student_has_owner")
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'teacher', 'student')", name=op.f("ck_users_role_allowed")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_users_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("link_token_hash", name=op.f("uq_users_link_token_hash")),
    )
    op.create_index(op.f("ix_users_owner_id"), "users", ["owner_id"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('platform', 'moodle')", name=op.f("ck_groups_source_allowed")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_groups_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
    )
    op.create_index(op.f("ix_groups_owner_id"), "groups", ["owner_id"], unique=False)
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_pipelines_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipelines")),
    )
    op.create_index(op.f("ix_pipelines_owner_id"), "pipelines", ["owner_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("check_method", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("tests", sa.Text(), nullable=True),
        sa.Column("rubric", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "check_method IN ('short_answer', 'code', 'long_answer')",
            name=op.f("ck_tasks_check_method_allowed"),
        ),
        sa.CheckConstraint("status IN ('draft', 'approved')", name=op.f("ck_tasks_status_allowed")),
        sa.CheckConstraint("difficulty >= 1", name=op.f("ck_tasks_difficulty_positive")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_tasks_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        "ix_tasks_search", "tasks", ["owner_id", "subject", "topic", "difficulty"], unique=False
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(student_id IS NULL) <> (group_id IS NULL)", name=op.f("ck_assignments_one_target")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_assignments_group_id_groups")
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], name=op.f("fk_assignments_pipeline_id_pipelines")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name=op.f("fk_assignments_student_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["users.id"], name=op.f("fk_assignments_teacher_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
    )
    op.create_index(
        op.f("ix_assignments_pipeline_id"), "assignments", ["pipeline_id"], unique=False
    )
    op.create_index(op.f("ix_assignments_teacher_id"), "assignments", ["teacher_id"], unique=False)
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_group_members_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_group_members_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "student_id", name=op.f("pk_group_members")),
    )
    op.create_table(
        "pipeline_versions",
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name=op.f("fk_pipeline_versions_pipeline_id_pipelines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pipeline_id", "version", name=op.f("pk_pipeline_versions")),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("teacher_id", sa.Uuid(), nullable=True),
        sa.Column("assignment_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'waiting', 'done', 'error')", name=op.f("ck_runs_status_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["assignments.id"], name=op.f("fk_runs_assignment_id_assignments")
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id", "pipeline_version"],
            ["pipeline_versions.pipeline_id", "pipeline_versions.version"],
            name="fk_runs_pipeline_version",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name=op.f("fk_runs_student_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["users.id"], name=op.f("fk_runs_teacher_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_student_id"), "runs", ["student_id"], unique=False)
    op.create_index("ix_runs_teacher_status", "runs", ["teacher_id", "status"], unique=False)
    op.create_index(
        "uq_runs_assignment_student",
        "runs",
        ["assignment_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("assignment_id IS NOT NULL"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_run", "events", ["run_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_run", table_name="events")
    op.drop_table("events")
    op.drop_index(
        "uq_runs_assignment_student",
        table_name="runs",
        postgresql_where=sa.text("assignment_id IS NOT NULL"),
    )
    op.drop_index("ix_runs_teacher_status", table_name="runs")
    op.drop_index(op.f("ix_runs_student_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_table("pipeline_versions")
    op.drop_table("group_members")
    op.drop_index(op.f("ix_assignments_teacher_id"), table_name="assignments")
    op.drop_index(op.f("ix_assignments_pipeline_id"), table_name="assignments")
    op.drop_table("assignments")
    op.drop_index("ix_tasks_search", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_pipelines_owner_id"), table_name="pipelines")
    op.drop_table("pipelines")
    op.drop_index(op.f("ix_groups_owner_id"), table_name="groups")
    op.drop_table("groups")
    op.drop_index(op.f("ix_users_owner_id"), table_name="users")
    op.drop_table("users")
