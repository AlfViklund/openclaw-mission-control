"""Add planner expansion audit and execution coverage fields.

Revision ID: c61d2e7f8a9b
Revises: f9c2d4a1b7e8
Create Date: 2026-04-05 23:55:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c61d2e7f8a9b"
down_revision = "f9c2d4a1b7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add execution coverage fields and planner expansion runs."""
    with op.batch_alter_table("planner_outputs") as batch_op:
        batch_op.add_column(
            sa.Column("epic_states", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("expansion_policy", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("materialized_task_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("remaining_scope_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("latest_expansion_at", sa.DateTime(), nullable=True)
        )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column("planner_output_id", sa.Uuid(), nullable=True)
        )
        batch_op.add_column(sa.Column("planner_epic_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("materialized_from", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("expansion_round", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_tasks_planner_output_id",
            ["planner_output_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_tasks_materialized_from",
            ["materialized_from"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_tasks_planner_output_id_planner_outputs",
            "planner_outputs",
            ["planner_output_id"],
            ["id"],
        )

    op.create_table(
        "planner_expansion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("planner_output_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("trigger", sa.String(), nullable=False, server_default="manual"),
        sa.Column("source_epic_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_task_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["planner_output_id"], ["planner_outputs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_planner_expansion_runs_planner_output_id",
        "planner_expansion_runs",
        ["planner_output_id"],
        unique=False,
    )
    op.create_index(
        "ix_planner_expansion_runs_board_id",
        "planner_expansion_runs",
        ["board_id"],
        unique=False,
    )
    op.create_index(
        "ix_planner_expansion_runs_status",
        "planner_expansion_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_planner_expansion_runs_trigger",
        "planner_expansion_runs",
        ["trigger"],
        unique=False,
    )


def downgrade() -> None:
    """Drop planner expansion audit and execution coverage fields."""
    op.drop_index("ix_planner_expansion_runs_trigger", table_name="planner_expansion_runs")
    op.drop_index("ix_planner_expansion_runs_status", table_name="planner_expansion_runs")
    op.drop_index(
        "ix_planner_expansion_runs_planner_output_id",
        table_name="planner_expansion_runs",
    )
    op.drop_index("ix_planner_expansion_runs_board_id", table_name="planner_expansion_runs")
    op.drop_table("planner_expansion_runs")

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint(
            "fk_tasks_planner_output_id_planner_outputs",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_tasks_materialized_from")
        batch_op.drop_index("ix_tasks_planner_output_id")
        batch_op.drop_column("expansion_round")
        batch_op.drop_column("materialized_from")
        batch_op.drop_column("planner_epic_id")
        batch_op.drop_column("planner_output_id")

    with op.batch_alter_table("planner_outputs") as batch_op:
        batch_op.drop_column("latest_expansion_at")
        batch_op.drop_column("remaining_scope_count")
        batch_op.drop_column("materialized_task_count")
        batch_op.drop_column("expansion_policy")
        batch_op.drop_column("epic_states")
