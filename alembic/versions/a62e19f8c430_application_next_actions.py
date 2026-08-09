"""application next actions

Revision ID: a62e19f8c430
Revises: f37a23d08c11
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a62e19f8c430"
down_revision: Union[str, Sequence[str], None] = "f37a23d08c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("next_action", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column(
        "applications",
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applications", "next_action_at")
    op.drop_column("applications", "next_action")
