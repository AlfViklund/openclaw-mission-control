"""Add board execution policy and run failure classification fields.

Revision ID: e7a4c2d1b9f0
Revises: c61d2e7f8a9b
Create Date: 2026-04-06 14:20:00.000000

"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "e7a4c2d1b9f0"
down_revision = "c61d2e7f8a9b"
branch_labels = None
depends_on = None

_DEFAULT_EXECUTION_POLICY = {
    "default_runtime": "opencode_cli",
    "allowed_runtimes": ["opencode_cli"],
    "build_approval_mode": "high_risk_only",
    "auto_run_next_stage": True,
    "show_runs_debug_ui": True,
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "execution_policy" not in board_columns:
        op.add_column(
            "boards",
            sa.Column(
                "execution_policy",
                sa.JSON(),
                nullable=False,
                server_default=sa.text(f"'{json.dumps(_DEFAULT_EXECUTION_POLICY)}'::json"),
            ),
        )
        op.alter_column("boards", "execution_policy", server_default=None)
    if "execution_runtime_state" not in board_columns:
        op.add_column(
            "boards",
            sa.Column(
                "execution_runtime_state",
                sa.JSON(),
                nullable=True,
            ),
        )

    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "failure_kind" not in run_columns:
        op.add_column("runs", sa.Column("failure_kind", sa.String(), nullable=True))
        op.create_index("ix_runs_failure_kind", "runs", ["failure_kind"], unique=False)
    if "retryable" not in run_columns:
        op.add_column(
            "runs",
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.alter_column("runs", "retryable", server_default=None)

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "review_mode" not in task_columns:
        op.add_column("tasks", sa.Column("review_mode", sa.String(), nullable=True))
        op.create_index("ix_tasks_review_mode", "tasks", ["review_mode"], unique=False)

    event_columns = {column["name"] for column in inspector.get_columns("activity_events")}
    if "payload_json" not in event_columns:
        op.add_column("activity_events", sa.Column("payload_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "retryable" in run_columns:
        op.drop_column("runs", "retryable")
    if "failure_kind" in run_columns:
        op.drop_index("ix_runs_failure_kind", table_name="runs")
        op.drop_column("runs", "failure_kind")

    event_columns = {column["name"] for column in inspector.get_columns("activity_events")}
    if "payload_json" in event_columns:
        op.drop_column("activity_events", "payload_json")

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "review_mode" in task_columns:
        op.drop_index("ix_tasks_review_mode", table_name="tasks")
        op.drop_column("tasks", "review_mode")

    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "execution_runtime_state" in board_columns:
        op.drop_column("boards", "execution_runtime_state")
    if "execution_policy" in board_columns:
        op.drop_column("boards", "execution_policy")
