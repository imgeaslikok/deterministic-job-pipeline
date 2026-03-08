"""
Integration tests for stuck RUNNING job recovery.

Covers sweeper-based recovery of jobs left in RUNNING state
beyond the configured execution timeout.
"""

from datetime import timedelta

from sqlalchemy import select

from src.core.utils import now_utc
from src.jobs import pipeline
from src.jobs.enums import JobStatus
from src.jobs.service import submit_job
from src.outbox.enums import OutboxStatus
from src.outbox.events import JOB_DISPATCH_REQUESTED
from src.outbox.models import OutboxEvent
from src.tests.utils import generate_idempotency_key


def test_reset_stuck_running_jobs_resets_status_and_enqueues_dispatch_event(
    db_session, uow
):
    """A stale RUNNING job should be reset to PENDING and re-enqueued."""
    job = submit_job(
        uow,
        job_type="demo.sweeper.stuck",
        payload={},
        idempotency_key=generate_idempotency_key("sweeper-stuck"),
    )
    uow.commit()

    stale_time = now_utc() - timedelta(seconds=301)

    job.status = JobStatus.RUNNING
    job.updated_at = stale_time
    job.last_error = None
    db_session.add(job)
    db_session.commit()

    before_events = [
        event
        for event in db_session.execute(select(OutboxEvent)).scalars().all()
        if event.event_type == JOB_DISPATCH_REQUESTED
        and (event.payload or {}).get("job_id") == job.id
    ]

    reset_count = pipeline.reset_stuck_running_jobs(
        db_session,
        max_execution_seconds=300,
    )
    db_session.commit()
    db_session.expire_all()

    recovered_job = db_session.get(type(job), job.id)
    assert recovered_job is not None
    assert recovered_job.status == JobStatus.PENDING
    assert recovered_job.last_error == "Reset from RUNNING by sweeper"

    after_events = [
        event
        for event in db_session.execute(select(OutboxEvent)).scalars().all()
        if event.event_type == JOB_DISPATCH_REQUESTED
        and (event.payload or {}).get("job_id") == job.id
    ]

    assert reset_count >= 1
    assert len(after_events) == len(before_events) + 1
    assert after_events[-1].status == OutboxStatus.PENDING
