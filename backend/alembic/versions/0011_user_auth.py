"""user auth: password_hash + updated_at

Revision ID: 0011_user_auth
Revises: 0010_run_metrics_cost_model
Create Date: 2026-08-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_user_auth"
down_revision: str | None = "0010_run_metrics_cost_model"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Both columns are added as NULLABLE so that existing demo users
    # (created before auth existed) keep working and are NOT dropped. Those
    # legacy rows simply have ``password_hash = NULL`` and cannot log in until
    # a password is set — which is safe (no data loss, no migration failure on
    # production Neon Postgres).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("password_hash", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("password_hash")
