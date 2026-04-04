"""add execution runs and artifacts tables

Revision ID: 0c1d6d8e4e4f
Revises: fa6e83f8d9a1
Create Date: 2026-04-01 03:35:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0c1d6d8e4e4f"
down_revision = "fa6e83f8d9a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("board_id", sa.Uuid(), sa.ForeignKey("boards.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="task"),
        sa.Column("runtime_kind", sa.String(length=32), nullable=False, server_default="opencode"),
        sa.Column("runtime_session_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("current_phase", sa.String(length=32), nullable=False, server_default="plan"),
        sa.Column("plan_summary", sa.Text(), nullable=True),
        sa.Column("build_summary", sa.Text(), nullable=True),
        sa.Column("test_summary", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_state", sa.JSON(), nullable=True),
        sa.Column("recovery_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_runs_board_id", "execution_runs", ["board_id"])
    op.create_index("ix_execution_runs_task_id", "execution_runs", ["task_id"])
    op.create_index("ix_execution_runs_agent_id", "execution_runs", ["agent_id"])
    op.create_index("ix_execution_runs_status", "execution_runs", ["status"])
    op.create_index("ix_execution_runs_current_phase", "execution_runs", ["current_phase"])
    op.create_index("ix_execution_runs_runtime_session_key", "execution_runs", ["runtime_session_key"])
    op.create_index("ix_execution_runs_created_at", "execution_runs", ["created_at"])

    op.create_table(
        "execution_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("execution_run_id", sa.Uuid(), sa.ForeignKey("execution_runs.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("artifact_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_artifacts_execution_run_id", "execution_artifacts", ["execution_run_id"])
    op.create_index("ix_execution_artifacts_kind", "execution_artifacts", ["kind"])
    op.create_index("ix_execution_artifacts_created_at", "execution_artifacts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_artifacts_created_at", table_name="execution_artifacts")
    op.drop_index("ix_execution_artifacts_kind", table_name="execution_artifacts")
    op.drop_index("ix_execution_artifacts_execution_run_id", table_name="execution_artifacts")
    op.drop_table("execution_artifacts")

    op.drop_index("ix_execution_runs_created_at", table_name="execution_runs")
    op.drop_index("ix_execution_runs_runtime_session_key", table_name="execution_runs")
    op.drop_index("ix_execution_runs_current_phase", table_name="execution_runs")
    op.drop_index("ix_execution_runs_status", table_name="execution_runs")
    op.drop_index("ix_execution_runs_agent_id", table_name="execution_runs")
    op.drop_index("ix_execution_runs_task_id", table_name="execution_runs")
    op.drop_index("ix_execution_runs_board_id", table_name="execution_runs")
    op.drop_table("execution_runs")
