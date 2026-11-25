"""add wipe password

Revision ID: 7d1e3f9a2b64
Revises: c3a91e4b7d20
Create Date: 2026-11-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d1e3f9a2b64"
down_revision: str | None = "c3a91e4b7d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("wipe_password_hash", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("wipe_password_hash")
