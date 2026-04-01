"""Add artifacts table for spec and artifact hub.

Revision ID: ab12cd34ef56
Revises: fa6e83f8d9a1
Create Date: 2026-04-01 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ab12cd34ef56"
down_revision = "fa6e83f8d9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create artifacts table for document/artifact storage."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("board_id", sa.Uuid(), sa.ForeignKey("boards.id"), nullable=False, index=True),
            sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=True, index=True),
            sa.Column("type", sa.String(), nullable=False, server_default="other", index=True),
            sa.Column("source", sa.String(), nullable=False, server_default="web", index=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("storage_path", sa.String(), nullable=False),
            sa.Column("checksum", sa.String(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True, index=True),
        )


def downgrade() -> None:
    """Drop artifacts table."""
    op.drop_table("artifacts")
