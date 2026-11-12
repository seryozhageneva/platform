"""Подключение к облаку — Яндекс Диску преподавателя (ADR 0036)."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_KIND_CHECK = "ck_connections_kind_allowed"


def upgrade() -> None:
    op.drop_constraint(op.f(_KIND_CHECK), "connections", type_="check")
    op.create_check_constraint(
        op.f(_KIND_CHECK), "connections", "kind IN ('moodle', 'telegram', 'cloud')"
    )


def downgrade() -> None:
    # Старая версия не умеет читать подключения облака.
    op.execute("DELETE FROM connections WHERE kind = 'cloud'")
    op.drop_constraint(op.f(_KIND_CHECK), "connections", type_="check")
    op.create_check_constraint(op.f(_KIND_CHECK), "connections", "kind IN ('moodle', 'telegram')")
