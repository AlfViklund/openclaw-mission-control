"""Add planner metadata fields to tasks table.

Revision ID: de45fg67hi89
Revises: cd34ef56gh78
Create Date: 2026-04-01 00:03:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "de45fg67hi89"
down_revision = "cd34ef56gh78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add planner metadata fields to tasks table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = [c["name"] for c in inspector.get_columns("tasks")]

    if "acceptance_criteria" not in columns:
        op.add_column("tasks", sa.Column("acceptance_criteria", sa.JSON(), nullable=False, server_default="[]"))
    if "estimate" not in columns:
        op.add_column("tasks", sa.Column("estimate", sa.String(), nullable=True))
    if "suggested_agent_role" not in columns:
        op.add_column("tasks", sa.Column("suggested_agent_role", sa.String(), nullable=True))
    if "planner_task_id" not in columns:
        op.add_column("tasks", sa.Column("planner_task_id", sa.String(), nullable=True))
    if "epic_id" not in columns:
        op.add_column("tasks", sa.Column("epic_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove planner metadata fields from tasks table."""
    op.drop_column("tasks", "epic_id")
    op.drop_column("tasks", "planner_task_id")
    op.drop_column("tasks", "suggested_agent_role")
    op.drop_column("tasks", "estimate")
    op.drop_column("tasks", "acceptance_criteria")
