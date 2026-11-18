"""add app state

Revision ID: 9b2f6c3e1a57
Revises: 4c1e9a7d2b10
Create Date: 2026-11-18 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b2f6c3e1a57"
down_revision: str | None = "4c1e9a7d2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_state")),
    )


def downgrade() -> None:
    op.drop_table("app_state")
