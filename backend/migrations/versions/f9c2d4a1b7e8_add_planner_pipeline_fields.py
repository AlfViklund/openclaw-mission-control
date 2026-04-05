"""Add planner pipeline document and phase tracking fields.

Revision ID: f9c2d4a1b7e8
Revises: a1b2c3d4e5f7, a9b1c2d3e4f7
Create Date: 2026-04-05 21:10:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f9c2d4a1b7e8"
down_revision = ("a1b2c3d4e5f7", "a9b1c2d3e4f7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add planner pipeline fields to planner_outputs."""
    with op.batch_alter_table("planner_outputs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pipeline_phase",
                sa.String(),
                nullable=False,
                server_default="queued",
            )
        )
        batch_op.add_column(
            sa.Column(
                "documents",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.add_column(
            sa.Column(
                "phase_statuses",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.create_index(
            "ix_planner_outputs_pipeline_phase",
            ["pipeline_phase"],
            unique=False,
        )


def downgrade() -> None:
    """Drop planner pipeline fields from planner_outputs."""
    with op.batch_alter_table("planner_outputs") as batch_op:
        batch_op.drop_index("ix_planner_outputs_pipeline_phase")
        batch_op.drop_column("phase_statuses")
        batch_op.drop_column("documents")
        batch_op.drop_column("pipeline_phase")
