"""
Application service for job submission and management.

Handles job creation, DLQ inspection, and retry orchestration.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.utils import tx
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
    Create (or reuse) a job and record a dispatch request in the outbox.
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

    return job


def list_dlq(db: Session, *, limit: int = 50) -> list[Job]:
    """List jobs currently in the DLQ state."""
    return repo.list_by_status(db, status=JobStatus.DEAD, limit=limit)


def get_job(db: Session, *, id: str) -> Job:
    """Fetch a job by id."""
    job = repo.get(db, id=id)
    if not job:
        raise JobNotFound(id)
    return job


def retry_from_dlq(db: Session, *, id: str, request_id: str | None = None) -> Job:
    """
    Reset a dead job to pending and enqueue it again via the outbox.
    """
    with tx(db):
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

        return job


def list_attempts(db: Session, *, job_id: str):
    """Return the execution attempt history for a job."""
    _ = get_job(db, id=job_id)
    return repo.list_attempts(db, job_id=job_id)


def _create_job_row(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    idempotency_key: str | None,
) -> Job:
    """Create a new job row or reuse an existing one via idempotency key."""
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
