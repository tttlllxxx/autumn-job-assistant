"""trusted funnel, persistent tasks, and application job link

Revision ID: 85b9c1d46f20
Revises: c8210928fe1c
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "85b9c1d46f20"
down_revision: Union[str, Sequence[str], None] = "c8210928fe1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_runs",
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_runs",
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_runs",
        sa.Column("rejection_reasons", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_applications_job_id_job_postings",
            "job_postings",
            ["job_id"],
            ["id"],
        )
    op.create_index("ix_applications_job_id", "applications", ["job_id"], unique=False)

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_runs_task_type", "task_runs", ["task_type"], unique=False)
    op.create_index("ix_task_runs_scope_key", "task_runs", ["scope_key"], unique=False)
    op.create_index("ix_task_runs_status", "task_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_runs_status", table_name="task_runs")
    op.drop_index("ix_task_runs_scope_key", table_name="task_runs")
    op.drop_index("ix_task_runs_task_type", table_name="task_runs")
    op.drop_table("task_runs")

    op.drop_index("ix_applications_job_id", table_name="applications")
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_constraint("fk_applications_job_id_job_postings", type_="foreignkey")
        batch_op.drop_column("job_id")

    op.drop_column("source_runs", "rejection_reasons")
    op.drop_column("source_runs", "rejected_count")
    op.drop_column("source_runs", "accepted_count")
