"""Загруженные файлы платформы: таблица `files` (ADR 0023).

Одна строка — один файл преподавателя или его ученика: описание, как у типа `File` из
контракта, и само содержимое. Размер всегда равен длине содержимого.

Номер: 0006
Предыдущая: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('document', 'code', 'image', 'other')",
            name=op.f("ck_files_kind_allowed"),
        ),
        sa.CheckConstraint(
            "size = octet_length(content)", name=op.f("ck_files_size_matches_content")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_files_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name=op.f("fk_files_student_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
    )
    op.create_index(op.f("ix_files_owner_id"), "files", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_files_owner_id"), table_name="files")
    op.drop_table("files")
