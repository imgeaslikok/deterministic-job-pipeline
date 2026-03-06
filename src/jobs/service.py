from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config.settings import settings

from . import repository as repo
from .enums import JobStatus
from .exceptions import IdempotencyKeyConflict, InvalidJobState, JobNotFound
from .models import Job
from .tasks import process_job


def _enqueue_job(*, job_id: str, request_id: str | None) -> None:
    """
    Enqueue job for background processing.

    In test environment we skip enqueue because tests
    explicitly call process_job.apply(...).
    """
    if settings.environment == "test":
        return

    headers = {"x_request_id": request_id} if request_id else None

    process_job.apply_async(args=(job_id,), headers=headers)


def submit_job(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
    request_id: str | None = None,
) -> Job:
    """
    Create (or reuse) and enqueue processing.
    """
    job = _create_job_row(
        db, job_type=job_type, payload=payload, idempotency_key=idempotency_key
    )
    db.commit()

    _enqueue_job(job_id=job.id, request_id=request_id)

    db.refresh(job)
    return job


def get_job(db: Session, *, id: str) -> Job:
    job = repo.get(db, id=id)
    if not job:
        raise JobNotFound(id)
    return job


def retry_from_dlq(db: Session, *, job_id: str, request_id: str | None = None) -> Job:
    """Reset a dead job back to pending and enqueue it."""
    job = get_job(db, id=job_id)
    if job.status != JobStatus.dead:
        raise InvalidJobState(job_id=job.id, status=job.status.value)

    job.status = JobStatus.pending
    job.last_error = None
    job.result = None
    repo.save(db, job)
    db.commit()

    _enqueue_job(job_id=job.id, request_id=request_id)

    db.refresh(job)
    return job


def list_attempts(db: Session, *, job_id: str):
    _ = get_job(db, id=job_id)
    return repo.list_attempts(db, job_id=job_id)


def _create_job_row(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None,
) -> Job:
    """Create (or reuse) a job row in the current transaction (no enqueue)."""
    if idempotency_key:
        existing = repo.get_by_idempotency_key(db, key=idempotency_key)
        if existing:
            if existing.job_type != job_type or (existing.payload or {}) != (
                payload or {}
            ):
                raise IdempotencyKeyConflict(idempotency_key)
            return existing

    try:
        return repo.create(
            db, job_type=job_type, payload=payload, idempotency_key=idempotency_key
        )
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = repo.get_by_idempotency_key(db, key=idempotency_key)
            if existing:
                if existing.job_type != job_type or (existing.payload or {}) != (
                    payload or {}
                ):
                    raise IdempotencyKeyConflict(idempotency_key)
                return existing
        raise
