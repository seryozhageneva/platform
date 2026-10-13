"""Журнал вызовов модели: таблица `llm_calls` (ADR 0012).

Одна строка — один вызов ИИ-модели: провайдер, модель, токены, задержка и, если вызов не
удался, короткое обозначение причины. Текста запроса и ответа в таблице нет.

Номер: 0002
Предыдущая: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_llm_calls_tokens_not_negative"),
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_llm_calls_latency_not_negative")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_llm_calls_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index("ix_llm_calls_run", "llm_calls", ["run_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_calls_run", table_name="llm_calls")
    op.drop_table("llm_calls")
