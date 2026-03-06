from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.outbox import service as outbox_service
from src.outbox.events import JOB_DISPATCH_REQUESTED

from . import repository as repo
from .enums import JobStatus
from .exceptions import IdempotencyKeyConflict, InvalidJobState, JobNotFound
from .models import Job


def submit_job(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
    request_id: str | None = None,
) -> Job:
    """
    Create (or reuse) a job row and record a dispatch request in the outbox.
    """
    job = _create_job_row(
        db,
        job_type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
    )

    outbox_service.create_event(
        db,
        event_type=JOB_DISPATCH_REQUESTED,
        payload={
            "job_id": job.id,
            "request_id": request_id,
        },
    )

    db.commit()
    db.refresh(job)
    return job


def list_dlq(db: Session, *, limit: int = 50) -> list[Job]:
    """List dead jobs for DLQ inspection and retry workflows."""
    return repo.list_by_status(db, status=JobStatus.DEAD, limit=limit)


def get_job(db: Session, *, id: str) -> Job:
    job = repo.get(db, id=id)
    if not job:
        raise JobNotFound(id)
    return job


def retry_from_dlq(db: Session, *, id: str, request_id: str | None = None) -> Job:
    """Reset a dead job back to pending and record a dispatch request in the outbox."""
    job = get_job(db, id=id)
    if job.status != JobStatus.DEAD:
        raise InvalidJobState(job_id=job.id, status=job.status.value)

    job.status = JobStatus.PENDING
    job.last_error = None
    job.result = None
    repo.save(db, job)

    outbox_service.create_event(
        db,
        event_type=JOB_DISPATCH_REQUESTED,
        payload={
            "job_id": job.id,
            "request_id": request_id,
        },
    )

    db.commit()
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
    """Create (or reuse) a job row in the current transaction."""
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
            db,
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
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
