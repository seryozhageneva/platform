"""Работы учеников: столбец `correct` — верно ли решена работа (ADR 0031).

Хранилище платформы отдаёт блоку результаты учеников, и «верно или нет» берётся из
вердикта, а не угадывается по баллу: у проверки по рубрике балл бывает частичным. У старых
работ столбец пуст.

Номер: 0009
Предыдущая: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("correct", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "correct")
