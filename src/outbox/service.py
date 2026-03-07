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
from .config import MAX_PUBLISH_RETRIES, OUTBOX_PUBLISH_BATCH_LIMIT
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


def _handle_unsupported_event(db: Session, *, event: OutboxEvent) -> None:
    """Mark an unsupported event type as failed."""
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


def _publish_job_dispatch_event(
    *,
    event: OutboxEvent,
    dispatch_job: JobDispatch,
) -> None:
    """Dispatch a JOB_DISPATCH_REQUESTED event."""
    payload = event.payload or {}

    dispatch_job(
        payload["job_id"],
        payload.get("request_id"),
    )


def _mark_event_published(db: Session, *, event: OutboxEvent) -> None:
    """Mark an event as successfully published."""
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


def _handle_publish_failure(
    db: Session,
    *,
    event: OutboxEvent,
    exc: Exception,
) -> None:
    """Handle publish failure and decide retry vs terminal failure."""
    error = str(exc)
    retry_count = int(event.retry_count or 0)

    decision = decide_publish_failure(
        exc=exc,
        retry_count=retry_count,
    )

    if decision == OutboxStatus.FAILED:
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
        return

    schedule_retry(
        db,
        event=event,
        error=error,
        now=now_utc(),
    )

    publisher_log(
        LogLevel.WARNING,
        OUTBOX_EVENT_RETRY_SCHEDULED,
        outbox_event=event,
        detail=error,
    )


def _publish_single_event(
    db: Session,
    *,
    event: OutboxEvent,
    dispatch_job: JobDispatch,
) -> bool:
    """
    Publish a single outbox event.

    Returns True if the event was successfully published.
    """

    if event.event_type != JOB_DISPATCH_REQUESTED:
        _handle_unsupported_event(db, event=event)
        return False

    try:
        _publish_job_dispatch_event(
            event=event,
            dispatch_job=dispatch_job,
        )

        _mark_event_published(db, event=event)
        return True

    except Exception as exc:
        db.rollback()

        refreshed = get_event(db, event_id=event.id)
        if refreshed is None:
            raise

        _handle_publish_failure(
            db,
            event=refreshed,
            exc=exc,
        )

        return False


def decide_publish_failure(
    *,
    exc: Exception,
    retry_count: int,
) -> OutboxStatus:
    """
    Decide whether a publish failure should be retried or marked terminal.

    The decision is based on the next retry count that would be recorded
    if the event were scheduled again.
    """
    if is_terminal_publish_error(exc):
        return OutboxStatus.FAILED

    next_retry_count = retry_count + 1
    if next_retry_count > MAX_PUBLISH_RETRIES:
        return OutboxStatus.FAILED

    return OutboxStatus.PENDING


def publish_pending_events(
    db: Session,
    *,
    dispatch_job: JobDispatch,
    limit: int = OUTBOX_PUBLISH_BATCH_LIMIT,
) -> int:
    """
    Publish pending outbox events.

    Claims pending events in batches under row locks, dispatches supported
    events, and updates their status.

    Each event is committed independently to guarantee durability of the
    publish outcome even if later events fail.
    """

    claimed_at = now_utc()
    events = repo.claim_pending_batch(db, now=claimed_at, limit=limit)

    published_count = 0

    for event in events:
        publisher_log(
            LogLevel.INFO,
            OUTBOX_EVENT_CLAIMED,
            outbox_event=event,
        )

        published = _publish_single_event(
            db,
            event=event,
            dispatch_job=dispatch_job,
        )

        # Event-level commit policy:
        # Each event outcome is committed independently.
        db.commit()

        if published:
            published_count += 1

    return published_count
