"""add semantic embedding column to memories (pgvector)

Revision ID: 0007_memory_embedding
Revises: 0006_fix_embedding_dim
Create Date: 2026-08-13 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# Must match app.infrastructure.embedding.EMBEDDING_DIM
EMBEDDING_DIM = 2048


# revision identifiers, used by Alembic.
revision: str = "0007_memory_embedding"
down_revision: str | None = "0006_fix_embedding_dim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure the pgvector extension exists (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Add the embedding column as nullable so existing memories are preserved.
    # Legacy rows keep a NULL embedding until backfilled.
    op.add_column(
        "memories",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    # Index to speed up user-scoped similarity scans.
    op.create_index(
        "ix_memories_user_id", "memories", ["user_id"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index("ix_memories_user_id", table_name="memories")
    op.drop_column("memories", "embedding")
