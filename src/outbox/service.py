from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from . import repository as repo
from .enums import OutboxStatus
from .events import JOB_DISPATCH_REQUESTED
from .models import OutboxEvent

JobDispatch = Callable[[str, str | None], None]


def create_event(
    db: Session,
    *,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    return repo.create(
        db,
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING,
    )


def get_event(db: Session, *, event_id: str) -> OutboxEvent | None:
    return repo.get(db, id=event_id)


def list_pending_events(db: Session, *, limit: int = 100) -> list[OutboxEvent]:
    return repo.list_pending(db, limit=limit)


def update_event(
    db: Session,
    *,
    event: OutboxEvent,
    status: OutboxStatus,
    error: str | None = None,
) -> OutboxEvent:
    event.status = status
    event.error = error
    return repo.save(db, event)


def publish_pending_events(
    db: Session,
    *,
    dispatch_job: JobDispatch,
    limit: int = 100,
) -> int:
    """
    Publish pending outbox events.

    Returns the number of successfully published events.
    """
    events = list_pending_events(db, limit=limit)
    published_count = 0

    for event in events:
        try:
            if event.event_type == JOB_DISPATCH_REQUESTED:
                payload = event.payload or {}
                dispatch_job(
                    payload["job_id"],
                    payload.get("request_id"),
                )
            else:
                raise ValueError(f"Unsupported outbox event type: {event.event_type}")

            update_event(db, event=event, status=OutboxStatus.PUBLISHED)
            db.commit()
            published_count += 1

        except Exception as exc:
            db.rollback()

            refreshed = get_event(db, event_id=event.id)
            if refreshed is None:
                raise

            update_event(
                db,
                event=refreshed,
                status=OutboxStatus.FAILED,
                error=str(exc),
            )
            db.commit()

    return published_count
