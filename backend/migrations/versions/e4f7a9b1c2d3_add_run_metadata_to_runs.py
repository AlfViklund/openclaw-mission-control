"""Add run_metadata column to runs.

Revision ID: e4f7a9b1c2d3
Revises: d1e2f3a4b5c6
Create Date: 2026-04-04 12:45:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4f7a9b1c2d3"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("runs")]

    if "run_metadata" not in columns:
        op.add_column(
            "runs",
            sa.Column("run_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        )
        op.alter_column("runs", "run_metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "run_metadata")
