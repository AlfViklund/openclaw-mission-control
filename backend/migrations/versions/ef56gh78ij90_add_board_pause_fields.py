"""Add pause controls to boards.

Revision ID: ef56gh78ij90
Revises: de45fg67hi89
Create Date: 2026-04-01 00:04:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ef56gh78ij90"
down_revision = "de45fg67hi89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("boards")]

    if "is_paused" not in columns:
        op.add_column("boards", sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "paused_reason" not in columns:
        op.add_column("boards", sa.Column("paused_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("boards", "paused_reason")
    op.drop_column("boards", "is_paused")
