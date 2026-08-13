"""add approvals table for human-in-the-loop high-risk tools

Revision ID: 0002_approvals
Revises: 0001_initial
Create Date: 2026-08-13 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_approvals"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])
    op.create_index("ix_approvals_conversation_id", "approvals", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_conversation_id", table_name="approvals")
    op.drop_index("ix_approvals_user_id", table_name="approvals")
    op.drop_table("approvals")
