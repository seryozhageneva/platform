"""Результаты кабинета: таблица `cabinet_results` (ADR 0026).

Одна строка — один результат запуска, который блок-получатель опубликовал для преподавателя
или для конкретного его ученика. Номер строки вычисляется из запуска, узла и ключа
результата, поэтому повтор блока не создаёт вторую запись.

Номер: 0007
Предыдущая: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cabinet_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_cabinet_results_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_cabinet_results_run_id_runs")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name=op.f("fk_cabinet_results_student_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cabinet_results")),
    )
    for column in ("owner_id", "run_id", "student_id"):
        op.create_index(
            op.f(f"ix_cabinet_results_{column}"), "cabinet_results", [column], unique=False
        )


def downgrade() -> None:
    for column in ("student_id", "run_id", "owner_id"):
        op.drop_index(op.f(f"ix_cabinet_results_{column}"), table_name="cabinet_results")
    op.drop_table("cabinet_results")
