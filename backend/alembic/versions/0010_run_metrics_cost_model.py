"""run_metrics: model-aware cost + usage availability

Revision ID: 0010_run_metrics_cost_model
Revises: 0009_conversation_updated_at
Create Date: 2026-08-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_run_metrics_cost_model"
down_revision: str | None = "0009_conversation_updated_at"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Make estimated_cost_usd nullable so "unavailable" is distinct from 0.0.
    with op.batch_alter_table("run_metrics") as batch_op:
        batch_op.alter_column(
            "estimated_cost_usd",
            existing_type=sa.Float(),
            nullable=True,
            server_default=None,
        )
        batch_op.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("usage_available", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("run_metrics") as batch_op:
        batch_op.drop_column("usage_available")
        batch_op.drop_column("model")
        batch_op.alter_column(
            "estimated_cost_usd",
            existing_type=sa.Float(),
            nullable=False,
            server_default="0.0",
        )
