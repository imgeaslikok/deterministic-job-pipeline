"""
Repository helpers for transactional outbox events.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import OutboxStatus
from .models import OutboxEvent

T = TypeVar("T")


def save(db: Session, obj: T) -> T:
    """Persist an object and flush the session."""
    db.add(obj)
    db.flush()
    return obj


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


def list_pending(db: Session, *, limit: int = 100) -> list[OutboxEvent]:
    """List pending outbox events ordered by creation time."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def claim_next_pending(db: Session) -> OutboxEvent | None:
    """Return the next pending outbox event under a row lock."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    return db.execute(stmt).scalars().first()
