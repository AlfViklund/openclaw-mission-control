"""add spec artifacts and planner draft support

Revision ID: 2d3e4f5a6b7c
Revises: 0c1d6d8e4e4f
Create Date: 2026-04-01 03:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d3e4f5a6b7c"
down_revision = "0c1d6d8e4e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spec_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("board_id", sa.Uuid(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="markdown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_spec_artifacts_board_id", "spec_artifacts", ["board_id"])
    op.create_index("ix_spec_artifacts_source", "spec_artifacts", ["source"])
    op.create_index("ix_spec_artifacts_created_at", "spec_artifacts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_spec_artifacts_created_at", table_name="spec_artifacts")
    op.drop_index("ix_spec_artifacts_source", table_name="spec_artifacts")
    op.drop_index("ix_spec_artifacts_board_id", table_name="spec_artifacts")
    op.drop_table("spec_artifacts")
