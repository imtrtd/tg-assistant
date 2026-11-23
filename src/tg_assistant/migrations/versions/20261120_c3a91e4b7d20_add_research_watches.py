"""add research watches

Revision ID: c3a91e4b7d20
Revises: 9b2f6c3e1a57
Create Date: 2026-11-20 03:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a91e4b7d20"
down_revision: str | None = "9b2f6c3e1a57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_watches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("term_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_watches")),
        sa.UniqueConstraint("chat_id", "term_key", name=op.f("uq_research_watches_chat_id")),
    )
    with op.batch_alter_table("research_watches", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_research_watches_chat_id"), ["chat_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_research_watches_user_id"), ["user_id"], unique=False)

    op.create_table(
        "research_seen_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watch_id", sa.Integer(), nullable=False),
        sa.Column("peer_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("found_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["watch_id"],
            ["research_watches.id"],
            name=op.f("fk_research_seen_posts_watch_id_research_watches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_seen_posts")),
        sa.UniqueConstraint(
            "watch_id",
            "peer_id",
            "message_id",
            name=op.f("uq_research_seen_posts_watch_id"),
        ),
    )
    with op.batch_alter_table("research_seen_posts", schema=None) as batch_op:
        batch_op.create_index("ix_research_seen_posts_watch_id", ["watch_id"], unique=False)


def downgrade() -> None:
    op.drop_table("research_seen_posts")
    op.drop_table("research_watches")
