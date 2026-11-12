"""Контакты для уведомлений и подключения Telegram (ADR 0033)."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_KIND_CHECK = "ck_connections_kind_allowed"


def upgrade() -> None:
    op.add_column("users", sa.Column("notification_email", sa.Text(), nullable=True))
    op.drop_constraint(op.f(_KIND_CHECK), "connections", type_="check")
    op.create_check_constraint(op.f(_KIND_CHECK), "connections", "kind IN ('moodle', 'telegram')")


def downgrade() -> None:
    # Старая версия не умеет читать подключения Telegram.
    op.execute("DELETE FROM connections WHERE kind = 'telegram'")
    op.drop_constraint(op.f(_KIND_CHECK), "connections", type_="check")
    op.create_check_constraint(op.f(_KIND_CHECK), "connections", "kind IN ('moodle')")
    op.drop_column("users", "notification_email")
