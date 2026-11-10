"""Личные ссылки и сеансы входа (ADR 0019)."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("link_expires_at", sa.DateTime(timezone=True)))
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_login_sessions_user_id"), "login_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("login_sessions")
    op.drop_column("users", "link_expires_at")
