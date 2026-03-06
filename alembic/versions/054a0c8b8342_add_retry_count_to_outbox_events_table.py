"""add retry_count to outbox_events table

Revision ID: 054a0c8b8342
Revises: ae058db4cf1b
Create Date: 2026-03-06 19:32:01.656498

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "054a0c8b8342"
down_revision: Union[str, Sequence[str], None] = "ae058db4cf1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "outbox_events",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("outbox_events", "retry_count", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("outbox_events", "published_at")
    op.drop_column("outbox_events", "next_attempt_at")
    op.drop_column("outbox_events", "retry_count")
