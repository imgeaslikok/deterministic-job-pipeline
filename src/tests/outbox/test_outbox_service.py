"""
Tests for the transactional outbox workflow.

Verifies event creation and publishing behavior.
"""

from __future__ import annotations

from sqlalchemy import select

from src.jobs.service import submit_job
from src.outbox import repository as repo
from src.outbox.enums import OutboxStatus
from src.outbox.events import JOB_DISPATCH_REQUESTED
from src.outbox.models import OutboxEvent
from src.outbox.service import publish_pending_events
from src.tests.utils import generate_idempotency_key


def test_submit_job_creates_pending_outbox_event(db_session):
    """Submitting a job should create a pending outbox dispatch event."""
    job = submit_job(
        db_session,
        job_type="demo.outbox",
        payload={"x": 1},
        idempotency_key=generate_idempotency_key("outbox-submit"),
        request_id="req-123",
    )
    db_session.commit()

    events = repo.list_pending(db_session, limit=100)

    event = next(
        e
        for e in events
        if e.event_type == JOB_DISPATCH_REQUESTED
        and (e.payload or {}).get("job_id") == job.id
    )

    assert event.status == OutboxStatus.PENDING
    assert event.payload == {
        "job_id": job.id,
        "request_id": "req-123",
    }


def test_publish_pending_events_dispatches_and_marks_event_published(db_session):
    """Publishing events should dispatch the job and mark the event as published."""
    dispatched: list[tuple[str, str | None]] = []

    job = submit_job(
        db_session,
        job_type="demo.outbox.publish.success",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-publish-success"),
        request_id="req-success",
    )
    db_session.commit()

    def fake_dispatch(job_id: str, request_id: str | None) -> None:
        dispatched.append((job_id, request_id))

    published_count = publish_pending_events(
        db_session,
        dispatch_job=fake_dispatch,
    )

    db_session.expire_all()

    stmt = select(OutboxEvent)
    events = list(db_session.execute(stmt).scalars().all())

    event = next(
        e
        for e in events
        if e.event_type == JOB_DISPATCH_REQUESTED
        and (e.payload or {}).get("job_id") == job.id
    )

    assert published_count >= 1
    assert (job.id, "req-success") in dispatched
    assert event.status == OutboxStatus.PUBLISHED
    assert event.error is None


def test_publish_pending_events_marks_event_failed_when_dispatch_fails(db_session):
    """Failed dispatch should mark the outbox event as failed."""
    job = submit_job(
        db_session,
        job_type="demo.outbox.publish.failed",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-publish-failed"),
        request_id="req-failed",
    )
    db_session.commit()

    def failing_dispatch(job_id: str, request_id: str | None) -> None:
        raise RuntimeError("dispatch failed")

    published_count = publish_pending_events(
        db_session,
        dispatch_job=failing_dispatch,
    )

    db_session.expire_all()

    stmt = select(OutboxEvent)
    events = list(db_session.execute(stmt).scalars().all())

    event = next(
        e
        for e in events
        if e.event_type == JOB_DISPATCH_REQUESTED
        and (e.payload or {}).get("job_id") == job.id
    )

    assert published_count == 0
    assert event.status == OutboxStatus.FAILED
    assert event.error == "dispatch failed"
