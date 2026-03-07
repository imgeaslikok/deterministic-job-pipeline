"""
Application service for transactional outbox events.

Handles event creation, state updates, and publishing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.core.enums import LogLevel
from src.core.utils import now_utc
from src.db.repository import save

from . import repository as repo
from .config import MAX_PUBLISH_RETRIES
from .enums import OutboxStatus
from .events import (
    JOB_DISPATCH_REQUESTED,
    OUTBOX_EVENT_CLAIMED,
    OUTBOX_EVENT_FAILED,
    OUTBOX_EVENT_PUBLISHED,
    OUTBOX_EVENT_RETRY_SCHEDULED,
)
from .messages import unsupported_event_type_error
from .models import OutboxEvent
from .utils import backoff_delay_seconds, is_terminal_publish_error, publisher_log

JobDispatch = Callable[[str, str | None], None]


def create_event(
    db: Session,
    *,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    """
    Create a new outbox event.
    """

    return repo.create(
        db,
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING,
    )


def get_event(db: Session, *, event_id: str) -> OutboxEvent | None:
    """
    Fetch an outbox event by id.
    """

    return repo.get(db, id=event_id)


def list_pending_events(db: Session, *, limit: int = 100) -> list[OutboxEvent]:
    """
    Return pending outbox events.
    """

    return repo.list_pending(db, limit=limit)


def update_event(
    db: Session,
    *,
    event: OutboxEvent,
    status: OutboxStatus,
    error: str | None = None,
    published_at: datetime | None = None,
) -> OutboxEvent:
    """
    Update the status of an outbox event.
    """

    event.status = status
    event.error = error
    event.published_at = published_at
    event.next_attempt_at = None
    return save(db, event)


def schedule_retry(
    db: Session,
    *,
    event: OutboxEvent,
    error: str,
    now: datetime,
) -> OutboxEvent:
    """
    Schedule a retry for a transient publish failure.
    """

    event.status = OutboxStatus.PENDING
    event.error = error
    event.retry_count = int(event.retry_count or 0) + 1
    event.published_at = None
    event.next_attempt_at = now + timedelta(
        seconds=backoff_delay_seconds(event.retry_count)
    )
    return save(db, event)


def publish_pending_events(
    db: Session,
    *,
    dispatch_job: JobDispatch,
    limit: int = 100,
) -> int:
    """
    Publish pending outbox events.

    Claims pending events one by one under row locks, dispatches supported
    events, and updates their status. Returns the number of successfully
    published events.
    """

    published_count = 0

    while published_count < limit:
        event = repo.claim_next_pending(db, now=now_utc())
        if event is None:
            break

        publisher_log(
            LogLevel.INFO,
            OUTBOX_EVENT_CLAIMED,
            outbox_event=event,
        )

        if event.event_type != JOB_DISPATCH_REQUESTED:
            error = unsupported_event_type_error(event.event_type)
            update_event(
                db,
                event=event,
                status=OutboxStatus.FAILED,
                error=error,
            )
            publisher_log(
                LogLevel.ERROR,
                OUTBOX_EVENT_FAILED,
                outbox_event=event,
                detail=error,
            )
            db.commit()
            continue

        try:
            payload = event.payload or {}
            dispatch_job(
                payload["job_id"],
                payload.get("request_id"),
            )

            update_event(
                db,
                event=event,
                status=OutboxStatus.PUBLISHED,
                published_at=now_utc(),
            )
            publisher_log(
                LogLevel.INFO,
                OUTBOX_EVENT_PUBLISHED,
                outbox_event=event,
            )
            db.commit()
            published_count += 1

        except Exception as exc:
            db.rollback()

            refreshed = get_event(db, event_id=event.id)
            if refreshed is None:
                raise

            error = str(exc)
            retry_count = int(refreshed.retry_count or 0)

            if is_terminal_publish_error(exc) or retry_count >= MAX_PUBLISH_RETRIES:
                update_event(
                    db,
                    event=refreshed,
                    status=OutboxStatus.FAILED,
                    error=error,
                )
                publisher_log(
                    LogLevel.ERROR,
                    OUTBOX_EVENT_FAILED,
                    outbox_event=refreshed,
                    detail=error,
                )
            else:
                schedule_retry(
                    db,
                    event=refreshed,
                    error=error,
                    now=now_utc(),
                )
                publisher_log(
                    LogLevel.WARNING,
                    OUTBOX_EVENT_RETRY_SCHEDULED,
                    outbox_event=refreshed,
                    detail=error,
                )

            db.commit()

    return published_count
