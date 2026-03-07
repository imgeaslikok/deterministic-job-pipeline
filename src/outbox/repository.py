"""
Repository helpers for transactional outbox events.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.db.repository import save

from .config import OUTBOX_PUBLISH_BATCH_LIMIT
from .enums import OutboxStatus
from .models import OutboxEvent


def create(
    db: Session,
    *,
    event_type: str,
    payload: dict,
    status: OutboxStatus = OutboxStatus.PENDING,
) -> OutboxEvent:
    """Create a new outbox event."""
    event = OutboxEvent(
        event_type=event_type,
        payload=payload,
        status=status,
    )
    return save(db, event)


def get(db: Session, *, id: str) -> OutboxEvent | None:
    """Fetch an outbox event by id."""
    return db.get(OutboxEvent, id)


def list_pending(
    db: Session, *, limit: int = OUTBOX_PUBLISH_BATCH_LIMIT
) -> list[OutboxEvent]:
    """List pending outbox events ordered by creation time."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def claim_pending_batch(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> list[OutboxEvent]:
    """
    Return the next publishable outbox events under row locks.

    Uses FOR UPDATE SKIP LOCKED so that concurrent publishers can safely
    claim disjoint batches without processing the same event twice.
    """
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .where(
            or_(
                OutboxEvent.next_attempt_at.is_(None),
                OutboxEvent.next_attempt_at <= now,
            )
        )
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())
