"""remove failed from job status

Revision ID: 2d29bcb4a9b0
Revises: b02e400bf69d
Create Date: 2026-03-07 20:19:40.278141
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d29bcb4a9b0"
down_revision: Union[str, Sequence[str], None] = "b02e400bf69d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE jobs SET status = 'dead' WHERE status = 'failed'")
    op.execute("ALTER TYPE job_status RENAME TO job_status_old")
    op.execute(
        "CREATE TYPE job_status AS ENUM ('pending', 'running', 'completed', 'dead')"
    )
    op.execute(
        "ALTER TABLE jobs "
        "ALTER COLUMN status TYPE job_status "
        "USING status::text::job_status"
    )
    op.execute("DROP TYPE job_status_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE job_status RENAME TO job_status_old")
    op.execute(
        "CREATE TYPE job_status AS ENUM "
        "('pending', 'running', 'completed', 'failed', 'dead')"
    )
    op.execute(
        "ALTER TABLE jobs "
        "ALTER COLUMN status TYPE job_status "
        "USING status::text::job_status"
    )
    op.execute("DROP TYPE job_status_old")
