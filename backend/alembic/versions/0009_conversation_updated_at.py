"""add updated_at to conversations

Revision ID: 0009_conversation_updated_at
Revises: 0008_observability
Create Date: 2026-08-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_conversation_updated_at"
down_revision: str | None = "0008_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The `title` column already exists (created in 0001_initial). Only add the
    # missing `updated_at` column so conversations can be sorted by recency
    # without touching or losing existing data.
    op.add_column(
        "conversations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    # Backfill existing rows with their created_at so ordering is sensible.
    op.execute(
        "UPDATE conversations SET updated_at = created_at WHERE updated_at IS NULL"
    )
    op.alter_column("conversations", "updated_at", nullable=False)
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_column("conversations", "updated_at")
