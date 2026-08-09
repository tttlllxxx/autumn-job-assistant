"""configurable job targets

Revision ID: f37a23d08c11
Revises: 85b9c1d46f20
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f37a23d08c11"
down_revision: Union[str, Sequence[str], None] = "85b9c1d46f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("target_graduation_year", sa.String(length=4), nullable=False, server_default="2027"),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column(
            "target_recruitment_types",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"校园招聘\"]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "target_recruitment_types")
    op.drop_column("candidate_profiles", "target_graduation_year")
