"""Add pipeline runtime state, review mode, and activity payload fields.

Revision ID: a4f6d9c2b1e3
Revises: e7a4c2d1b9f0
Create Date: 2026-04-06 16:05:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4f6d9c2b1e3"
down_revision = "e7a4c2d1b9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    board_columns = {column["name"] for column in inspector.get_columns("boards")}
    if "execution_runtime_state" not in board_columns:
        op.add_column("boards", sa.Column("execution_runtime_state", sa.JSON(), nullable=True))

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
