"""
Repository helpers for jobs and job attempts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.db.repository import save, save_and_refresh

from .enums import AttemptStatus, JobStatus
from .models import Job, JobAttempt


def list_by_status(
    db: Session,
    *,
    status: JobStatus,
    limit: int = 50,
    cursor_id: str | None = None,
) -> list[Job]:
    """
    List jobs filtered by status, ordered by created_at DESC.

    cursor_id — opaque cursor: pass the id of the last job from the previous
    page to fetch the next page. Implements keyset pagination on (created_at, id).
    """
    stmt = select(Job).where(Job.status == status)

    if cursor_id is not None:
        cursor_job = db.get(Job, cursor_id)
        if cursor_job is not None:
            stmt = stmt.where(
                or_(
                    Job.created_at < cursor_job.created_at,
                    and_(
                        Job.created_at == cursor_job.created_at,
                        Job.id < cursor_id,
                    ),
                )
            )

    stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
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
