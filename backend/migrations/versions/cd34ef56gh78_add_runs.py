"""Add runs table for agent execution tracking.

Revision ID: cd34ef56gh78
Revises: bc23de45fg67
Create Date: 2026-04-01 00:02:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cd34ef56gh78"
down_revision = "bc23de45fg67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create runs table for agent execution tracking."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("runs"):
        op.create_table(
            "runs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
            sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=True, index=True),
            sa.Column("runtime", sa.String(), nullable=False, server_default="acp", index=True),
            sa.Column("stage", sa.String(), nullable=False, server_default="plan", index=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued", index=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("temperature", sa.Float(), nullable=True),
            sa.Column("permissions_profile", sa.String(), nullable=True),
            sa.Column("evidence_paths", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("summary", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """Drop runs table."""
    op.drop_table("runs")
