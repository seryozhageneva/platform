"""Подключения к внешним системам: таблица `connections` (ADR 0028).

Одна строка — подключение преподавателя к внешней системе одного вида (пока только Moodle):
адрес и токен. Токен хранится только зашифрованным ключом из `.env`.

Номер: 0008
Предыдущая: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=False),
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
        sa.CheckConstraint("kind IN ('moodle')", name=op.f("ck_connections_kind_allowed")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_connections_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
        sa.UniqueConstraint("owner_id", "kind", name=op.f("uq_connections_owner_id")),
    )
    op.create_index(op.f("ix_connections_owner_id"), "connections", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_connections_owner_id"), table_name="connections")
    op.drop_table("connections")
