"""
Tests for the transactional outbox workflow.

Verifies event creation and publishing behavior.
"""

from __future__ import annotations

from sqlalchemy import select

from src.core.utils import now_utc
from src.db.session import SessionLocal
from src.jobs.service import submit_job
from src.outbox import repository as repo
from src.outbox.enums import OutboxStatus
from src.outbox.events import JOB_DISPATCH_REQUESTED
from src.outbox.models import OutboxEvent
from src.outbox.service import MAX_PUBLISH_RETRIES, publish_pending_events
from src.tests.utils import generate_idempotency_key


def test_submit_job_creates_pending_outbox_event(db_session, uow):
    """Submitting a job should create a pending outbox dispatch event."""
    job = submit_job(
        uow,
        job_type="demo.outbox",
        payload={"x": 1},
        idempotency_key=generate_idempotency_key("outbox-submit"),
        request_id="req-123",
    )
    uow.commit()

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


def test_publish_pending_events_dispatches_and_marks_event_published(db_session, uow):
    """Publishing events should dispatch the job and mark the event as published."""
    dispatched: list[tuple[str, str | None]] = []

    job = submit_job(
        uow,
        job_type="demo.outbox.publish.success",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-publish-success"),
        request_id="req-success",
    )
    uow.commit()

    def fake_dispatch(job_id: str, request_id: str | None) -> None:
        dispatched.append((job_id, request_id))

    published_count = publish_pending_events(
        SessionLocal,
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


def test_publish_pending_events_schedules_retry_when_dispatch_fails(db_session, uow):
    """Failed dispatch should schedule a retry for the outbox event."""
    job = submit_job(
        uow,
        job_type="demo.outbox.publish.failed",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-publish-failed"),
        request_id="req-failed",
    )
    uow.commit()

    def failing_dispatch(job_id: str, request_id: str | None) -> None:
        raise RuntimeError("dispatch failed")

    published_count = publish_pending_events(
        SessionLocal,
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
    assert event.status == OutboxStatus.PENDING
    assert event.error == "dispatch failed"
    assert event.retry_count == 1
    assert event.next_attempt_at is not None


def test_publish_pending_events_skips_locked_events_and_publishes_next(db_session, uow):
    """Publishing should skip locked pending events and publish the next available one."""
    first_job = submit_job(
        uow,
        job_type="demo.outbox.locked.first",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-locked-first"),
        request_id="req-first",
    )
    second_job = submit_job(
        uow,
        job_type="demo.outbox.locked.second",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-locked-second"),
        request_id="req-second",
    )
    uow.commit()

    dispatched: list[tuple[str, str | None]] = []

    def fake_dispatch(job_id: str, request_id: str | None) -> None:
        dispatched.append((job_id, request_id))

    lock_session = SessionLocal()

    try:
        locked_ids = repo.get_pending_batch_ids(
            lock_session,
            now=now_utc(),
            limit=1,
        )

        assert locked_ids

        locked_event = repo.get(lock_session, id=locked_ids[0])
        assert locked_event is not None
        assert (locked_event.payload or {}).get("job_id") == first_job.id

        published_count = publish_pending_events(
            SessionLocal,
            dispatch_job=fake_dispatch,
            limit=10,
        )

        db_session.expire_all()

        stmt = select(OutboxEvent)
        events = list(db_session.execute(stmt).scalars().all())

        first_event = next(
            e
            for e in events
            if e.event_type == JOB_DISPATCH_REQUESTED
            and (e.payload or {}).get("job_id") == first_job.id
        )
        second_event = next(
            e
            for e in events
            if e.event_type == JOB_DISPATCH_REQUESTED
            and (e.payload or {}).get("job_id") == second_job.id
        )

        assert published_count == 1
        assert (second_job.id, "req-second") in dispatched
        assert (first_job.id, "req-first") not in dispatched
        assert first_event.status == OutboxStatus.PENDING
        assert second_event.status == OutboxStatus.PUBLISHED
        assert second_event.error is None

    finally:
        lock_session.rollback()
        lock_session.close()


def test_publish_pending_events_drains_all_when_batch_is_full(db_session, uow):
    """publish_pending_events should keep processing until the backlog is cleared."""
    job_ids = []
    for i in range(3):
        job = submit_job(
            uow,
            job_type=f"demo.outbox.drain.{i}",
            payload={},
            idempotency_key=generate_idempotency_key(f"outbox-drain-{i}"),
            request_id=f"req-drain-{i}",
        )
        job_ids.append(job.id)
    uow.commit()

    dispatched: list[str] = []

    def fake_dispatch(job_id: str, request_id: str | None) -> None:
        dispatched.append(job_id)

    # batch_size=1 forces multiple loop iterations to clear all 3 events
    published_count = publish_pending_events(
        SessionLocal,
        dispatch_job=fake_dispatch,
        limit=1,
    )

    assert published_count >= 3
    for job_id in job_ids:
        assert job_id in dispatched


def test_publish_pending_events_marks_event_failed_after_retry_limit(db_session, uow):
    """Transient dispatch failure should become terminal after retry exhaustion."""
    job = submit_job(
        uow,
        job_type="demo.outbox.publish.retry.exhausted",
        payload={},
        idempotency_key=generate_idempotency_key("outbox-publish-retry-exhausted"),
        request_id="req-retry-exhausted",
    )
    uow.commit()

    def failing_dispatch(job_id: str, request_id: str | None) -> None:
        raise RuntimeError("temporary dispatch failure")

    for _ in range(MAX_PUBLISH_RETRIES + 1):
        publish_pending_events(
            SessionLocal,
            dispatch_job=failing_dispatch,
        )
        db_session.expire_all()

        event = next(
            e
            for e in db_session.execute(select(OutboxEvent)).scalars().all()
            if e.event_type == JOB_DISPATCH_REQUESTED
            and (e.payload or {}).get("job_id") == job.id
        )

        if event.status == OutboxStatus.PENDING:
            event.next_attempt_at = None
            db_session.commit()

    db_session.expire_all()

    event = next(
        e
        for e in db_session.execute(select(OutboxEvent)).scalars().all()
        if e.event_type == JOB_DISPATCH_REQUESTED
        and (e.payload or {}).get("job_id") == job.id
    )

    assert event.status == OutboxStatus.FAILED
    assert event.error == "temporary dispatch failure"
    assert event.retry_count == MAX_PUBLISH_RETRIES
    assert event.next_attempt_at is None
    assert event.published_at is None
