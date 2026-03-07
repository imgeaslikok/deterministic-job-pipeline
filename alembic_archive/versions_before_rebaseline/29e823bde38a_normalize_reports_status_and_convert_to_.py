"""normalize reports status and convert to enum

Revision ID: 29e823bde38a
Revises: 054a0c8b8342
Create Date: 2026-03-06 20:29:51.543009

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29e823bde38a"
down_revision: Union[str, Sequence[str], None] = "054a0c8b8342"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        UPDATE reports
        SET status = CASE status
            WHEN 'PENDING' THEN 'pending'
            WHEN 'READY' THEN 'ready'
            WHEN 'FAILED' THEN 'failed'
            ELSE status
        END
        """
    )

    report_status = sa.Enum(
        "pending",
        "ready",
        "failed",
        name="report_status",
    )
    report_status.create(op.get_bind(), checkfirst=True)

    op.execute(
        """
        ALTER TABLE reports
        ALTER COLUMN status TYPE report_status
        USING status::report_status
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE reports
        ALTER COLUMN status TYPE varchar
        USING status::text
        """
    )

    report_status = sa.Enum(
        "pending",
        "ready",
        "failed",
        name="report_status",
    )
    report_status.drop(op.get_bind(), checkfirst=True)
