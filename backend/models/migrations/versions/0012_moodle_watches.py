"""Запуск по событию Moodle: наблюдение и обработанные сдачи (ADR 0034)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moodle_watches",
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pipeline_id"),
    )
    op.create_table(
        "moodle_seen_submissions",
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.BigInteger(), nullable=False),
        sa.Column("submitted_at", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pipeline_id", "submission_id", "submitted_at"),
    )


def downgrade() -> None:
    op.drop_table("moodle_seen_submissions")
    op.drop_table("moodle_watches")
