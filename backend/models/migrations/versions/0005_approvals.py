"""Табличные подтверждения преподавателей."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("outcome", sa.Text()),
        sa.Column("response", JSONB(none_as_null=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(answered_at IS NULL AND outcome IS NULL AND response IS NULL) OR "
            "(answered_at IS NOT NULL AND outcome IS NOT NULL "
            "AND outcome IN ('approved', 'rejected') AND response IS NOT NULL)",
            name=op.f("ck_approvals_decision"),
        ),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])
    op.create_index(
        "uq_approvals_open_run",
        "approvals",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("answered_at IS NULL"),
    )
    # Сохранённые паузы сторонних блоков остаются доступны после обновления.
    op.execute("""
        INSERT INTO approvals (id, run_id, node_id, teacher_id, snapshot, opened_at)
        SELECT gen_random_uuid(), runs.id, waiting.item->>'node_id', runs.teacher_id,
               waiting.item->'data', runs.updated_at
        FROM runs
        CROSS JOIN LATERAL jsonb_array_elements(runs.state->'waiting') AS waiting(item)
        WHERE runs.status = 'waiting' AND runs.teacher_id IS NOT NULL
          AND waiting.item->>'who' = 'teacher' AND waiting.item->>'screen' = 'review_table'
    """)


def downgrade() -> None:
    op.drop_table("approvals")
