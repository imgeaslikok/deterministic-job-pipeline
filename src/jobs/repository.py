"""
Repository helpers for jobs and job attempts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.repository import save, save_and_refresh

from .enums import AttemptStatus, JobStatus
from .models import Job, JobAttempt


def list_by_status(db: Session, *, status: JobStatus, limit: int = 50) -> list[Job]:
    """List jobs filtered by status."""
    stmt = (
        select(Job)
        .where(Job.status == status)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_stuck_running(
    db: Session,
    *,
    stuck_before: datetime,
    limit: int = 50,
) -> list[Job]:
    """Return RUNNING jobs not updated since stuck_before."""
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.RUNNING)
        .where(Job.updated_at < stuck_before)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get(db: Session, *, id: str) -> Job | None:
    """Fetch a job by id."""
    return db.get(Job, id)


def get_by_idempotency_key(db: Session, *, key: str) -> Job | None:
    """Fetch a job by idempotency key."""
    stmt = select(Job).where(Job.idempotency_key == key)
    return db.execute(stmt).scalar_one_or_none()


def get_for_update(db: Session, *, id: str) -> Job | None:
    """Fetch a job with a row-level lock."""
    stmt = select(Job).where(Job.id == id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def create(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
) -> Job:
    """Create and persist a new job."""
    job = Job(
        job_type=job_type,
        payload=payload,
        status=JobStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    return save_and_refresh(db, job)


def list_attempts(db: Session, *, job_id: str) -> list[JobAttempt]:
    """Return the attempt history for a job."""
    stmt = (
        select(JobAttempt)
        .where(JobAttempt.job_id == job_id)
        .order_by(JobAttempt.attempt_no.asc(), JobAttempt.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def get_attempt(db: Session, *, job_id: str, attempt_no: int) -> JobAttempt | None:
    """Fetch a specific attempt for a job."""
    stmt = (
        select(JobAttempt)
        .where(JobAttempt.job_id == job_id)
        .where(JobAttempt.attempt_no == attempt_no)
    )
    return db.execute(stmt).scalars().first()


def create_attempt(
    db: Session,
    *,
    job_id: str,
    attempt_no: int,
    status: AttemptStatus,
    error: str | None = None,
    started_at: datetime | None = None,
) -> JobAttempt:
    """Create a new attempt record."""
    attempt = JobAttempt(
        job_id=job_id,
        attempt_no=attempt_no,
        status=status,
        error=error,
        started_at=started_at or datetime.now(UTC),
    )
    return save(db, attempt)


def update_attempt(
    db: Session,
    *,
    attempt: JobAttempt,
    status: AttemptStatus | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> JobAttempt:
    """Update fields of an existing attempt record."""
    if status is not None:
        attempt.status = status
    if error is not None:
        attempt.error = error
    if finished_at is not None:
        attempt.finished_at = finished_at
    return save(db, attempt)
