"""Add planner_outputs table for spec-to-backlog generation.

Revision ID: bc23de45fg67
Revises: ab12cd34ef56
Create Date: 2026-04-01 00:01:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "bc23de45fg67"
down_revision = "ab12cd34ef56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create planner_outputs table for backlog generation."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("planner_outputs"):
        op.create_table(
            "planner_outputs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("board_id", sa.Uuid(), sa.ForeignKey("boards.id"), nullable=False, index=True),
            sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=False, index=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft", index=True),
            sa.Column("json_schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("epics", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("tasks", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("parallelism_groups", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Drop planner_outputs table."""
    op.drop_table("planner_outputs")
