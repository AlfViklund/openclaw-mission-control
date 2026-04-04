"""Add automation_config field to boards.

Revision ID: d1e2f3a4b5c6
Revises: ef56gh78ij90
Create Date: 2026-04-04 12:32:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "ef56gh78ij90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("boards")]

    if "automation_config" not in columns:
        op.add_column(
            "boards",
            sa.Column("automation_config", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("boards", "automation_config")
