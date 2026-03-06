from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import AttemptStatus, JobStatus
from .models import Job, JobAttempt

T = TypeVar("T")


def _persist(db: Session, obj: T, *, refresh: bool = False) -> T:
    """Add + flush an ORM object (no commit)."""
    db.add(obj)
    db.flush()
    if refresh:
        db.refresh(obj)
    return obj


def get(db: Session, *, id: str) -> Job | None:
    return db.get(Job, id)


def get_by_idempotency_key(db: Session, *, key: str) -> Job | None:
    stmt = select(Job).where(Job.idempotency_key == key)
    return db.execute(stmt).scalar_one_or_none()


def get_for_update(db: Session, *, id: str) -> Job | None:
    stmt = select(Job).where(Job.id == id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def create(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
) -> Job:
    job = Job(
        job_type=job_type,
        payload=payload,
        status=JobStatus.pending,
        idempotency_key=idempotency_key,
    )
    return _persist(db, job, refresh=True)


def save(db: Session, job: Job) -> Job:
    return _persist(db, job)


def list_attempts(db: Session, *, job_id: str) -> list[JobAttempt]:
    stmt = (
        select(JobAttempt)
        .where(JobAttempt.job_id == job_id)
        .order_by(JobAttempt.attempt_no.asc(), JobAttempt.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def get_attempt(db: Session, *, job_id: str, attempt_no: int) -> JobAttempt | None:
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
    attempt = JobAttempt(
        job_id=job_id,
        attempt_no=attempt_no,
        status=status.value,
        error=error,
        started_at=started_at or datetime.now(UTC),
    )
    return _persist(db, attempt)


def update_attempt(
    db: Session,
    *,
    attempt: JobAttempt,
    status: AttemptStatus | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> JobAttempt:
    if status is not None:
        attempt.status = status.value
    if error is not None:
        attempt.error = error
    if finished_at is not None:
        attempt.finished_at = finished_at
    return _persist(db, attempt)
