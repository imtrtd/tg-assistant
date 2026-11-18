"""add cluster nodes

Revision ID: 4c1e9a7d2b10
Revises: e5337e2b7a99
Create Date: 2026-11-18 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c1e9a7d2b10"
down_revision: str | None = "e5337e2b7a99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cluster_nodes",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_leader", sa.Boolean(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_cluster_nodes")),
    )


def downgrade() -> None:
    op.drop_table("cluster_nodes")
