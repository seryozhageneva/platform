"""Работы учеников: таблица `submissions` (ADR 0016).

Одна строка — один принятый ответ ученика в уроке или работа, сданная в Moodle. Файл в
таблице не хранится — только ссылка на него. Оценка и статус вердикта пусты, пока работу
не проверили.

Номер: 0003
Предыдущая: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("form", sa.String(length=20), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("file", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("verdict_status", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('platform', 'moodle')", name=op.f("ck_submissions_source_allowed")
        ),
        sa.CheckConstraint(
            "form IN ('text', 'formula', 'code', 'photo')",
            name=op.f("ck_submissions_form_allowed"),
        ),
        sa.CheckConstraint(
            "verdict_status IN ('preliminary', 'confirmed')",
            name=op.f("ck_submissions_verdict_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_submissions_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name=op.f("fk_submissions_student_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_submissions_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submissions")),
    )
    op.create_index(op.f("ix_submissions_owner_id"), "submissions", ["owner_id"], unique=False)
    op.create_index(op.f("ix_submissions_student_id"), "submissions", ["student_id"], unique=False)
    op.create_index("ix_submissions_run", "submissions", ["run_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_submissions_run", table_name="submissions")
    op.drop_index(op.f("ix_submissions_student_id"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_owner_id"), table_name="submissions")
    op.drop_table("submissions")
