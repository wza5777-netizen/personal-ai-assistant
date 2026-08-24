"""user role column for RBAC.

Adds a ``role`` column to ``users`` so the application can distinguish
administrators from regular users (used by the create_admin script and the
RBAC permission model). The column is NULLABLE with a server default of
``'user'`` so existing rows are preserved and backfilled automatically — no
data loss and no migration failure on production Postgres.

Revision ID: 0012_user_role
Revises: 0011_user_auth
Create Date: 2026-08-24 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_user_role"
down_revision: str | None = "0011_user_auth"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(length=32),
                server_default="user",
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("role")
