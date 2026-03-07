"""rename type column to job_type

Revision ID: 8f47b4220e21
Revises: dae045f7388a
Create Date: 2026-03-06 12:23:13.487006

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f47b4220e21"
down_revision: Union[str, Sequence[str], None] = "dae045f7388a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jobs", "type", new_column_name="job_type")


def downgrade() -> None:
    op.alter_column("jobs", "job_type", new_column_name="type")
