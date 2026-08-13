"""fix embedding dimension to 2048 (doubao-embedding-vision)

Revision ID: 0006_fix_embedding_dim
Revises: 0005_knowledge
Create Date: 2026-08-13 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# Must match app.models.document.EMBEDDING_DIM
EMBEDDING_DIM = 2048


# revision identifiers, used by Alembic.
revision: str = "0006_fix_embedding_dim"
down_revision: str | None = "0005_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Correct the document_chunks.embedding column dimension to match the
    # actual embedding model output (doubao-embedding-vision -> 2048).
    # Note: ALTER COLUMN TYPE does not support bound parameters, so the
    # dimension is interpolated as a literal (it is a static constant).
    op.execute(
        sa.text(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM})")
    )


def downgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(2560)")
    )
