"""add outbox_events table

Revision ID: ae058db4cf1b
Revises: 8f47b4220e21
Create Date: 2026-03-06 15:53:31.634502

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae058db4cf1b"
down_revision: Union[str, Sequence[str], None] = "8f47b4220e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "outbox_events",
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "published", "failed", name="outbox_status"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_outbox_events_event_type"),
        "outbox_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_status"),
        "outbox_events",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_event_type"), table_name="outbox_events")
    op.drop_table("outbox_events")
