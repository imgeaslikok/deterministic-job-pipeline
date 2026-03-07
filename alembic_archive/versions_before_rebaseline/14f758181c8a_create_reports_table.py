"""create reports table

Revision ID: dae045f7388a
Revises: 5e133419c9ce
Create Date: 2026-03-05 08:20:36.438649

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "dae045f7388a"
down_revision: Union[str, Sequence[str], None] = "5e133419c9ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_job_id", "reports", ["job_id"], unique=False)
    op.create_index("ix_reports_status", "reports", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_job_id", table_name="reports")
    op.drop_table("reports")
