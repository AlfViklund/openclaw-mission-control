"""Add agent auth state machine columns.

Revision ID: a1b2c3d4e5f7
Revises: e4f7a9b1c2d3
Create Date: 2026-04-05 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "e4f7a9b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("agents")]

    if "agent_auth_mode" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "agent_auth_mode",
                sa.String(),
                nullable=False,
                server_default="legacy_hash",
            ),
        )

    if "agent_token_version" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "agent_token_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    if "pending_agent_token_version" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "pending_agent_token_version",
                sa.Integer(),
                nullable=True,
            ),
        )

    if "agent_auth_last_synced_at" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "agent_auth_last_synced_at",
                sa.DateTime(),
                nullable=True,
            ),
        )

    if "agent_auth_last_error" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "agent_auth_last_error",
                sa.Text(),
                nullable=True,
            ),
        )

    op.alter_column("agents", "agent_auth_mode", server_default=None)
    op.alter_column("agents", "agent_token_version", server_default=None)

    agents_table = sa.table(
        "agents",
        sa.column("agent_auth_mode", sa.String()),
        sa.column("agent_token_version", sa.Integer()),
        sa.column("pending_agent_token_version", sa.Integer()),
        sa.column("agent_token_hash", sa.String()),
    )

    op.execute(
        agents_table.update()
        .where(agents_table.c.agent_token_hash.isnot(None))
        .values(
            agent_auth_mode="legacy_hash",
            agent_token_version=1,
            pending_agent_token_version=None,
        )
    )

    op.execute(
        agents_table.update()
        .where(agents_table.c.agent_token_hash.is_(None))
        .values(
            agent_auth_mode="signed",
            agent_token_version=1,
        )
    )


def downgrade() -> None:
    op.drop_column("agents", "agent_auth_last_error")
    op.drop_column("agents", "agent_auth_last_synced_at")
    op.drop_column("agents", "pending_agent_token_version")
    op.drop_column("agents", "agent_token_version")
    op.drop_column("agents", "agent_auth_mode")
