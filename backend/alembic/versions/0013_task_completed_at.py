"""add completed_at to tasks

Adds a nullable ``completed_at`` timestamp to ``tasks`` so the agent can record
when a task was actually completed (written by complete_task). NULLABLE with no
default so existing rows are preserved without backfill.

Revision ID: 0013_task_completed_at
Revises: 0012_user_role
Create Date: 2026-08-27 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_task_completed_at"
down_revision: str | None = "0012_user_role"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("completed_at")
