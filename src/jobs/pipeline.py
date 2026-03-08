"""
Job state transition helpers.

Handles attempt lifecycle updates under database row locks.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import repository as repo
from .enums import AttemptStatus, JobStatus
from .exceptions import AttemptInvariantViolation
from .models import Job, JobAttempt
from .types import AttemptResult

_TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.DEAD}
)


def _is_terminal(status: JobStatus) -> bool:
    """Return whether the job is in a terminal state."""
    return status in _TERMINAL_STATUSES


def begin_attempt(db: Session, *, job_id: str, started_at: datetime) -> AttemptResult:
    """
    Start a job attempt under a row lock.

    Creates a running attempt row unless the job is missing, terminal,
    or already being processed by a concurrent invocation.
    """
    job = repo.get_for_update(db, id=job_id)
    if not job:
        return AttemptResult(False, "not_found", None, None)

    if _is_terminal(job.status):
        return AttemptResult(False, "terminal", job, None)

    attempt_no = int(job.attempts or 0) + 1

    job.status = JobStatus.RUNNING
    job.attempts = attempt_no
    job.last_error = None
    db.add(job)

    attempt = JobAttempt(
        job_id=job.id,
        attempt_no=attempt_no,
        status=AttemptStatus.RUNNING,
        started_at=started_at,
    )
    db.add(attempt)

    try:
        db.flush()  # single flush for both the job update and attempt row
    except IntegrityError:
        # Concurrent duplicate invocation.
        return AttemptResult(False, "duplicate", job, None)

    return AttemptResult(True, None, job, attempt_no)


def finalize_attempt(
    db: Session,
    *,
    job: Job,
    attempt_no: int,
    attempt_status: AttemptStatus,
    job_status: JobStatus,
    finished_at: datetime,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    """
    Finalize an attempt and update the job state.

    Accepts the already-locked job object from begin_attempt, avoiding
    a redundant SELECT FOR UPDATE round-trip.

    Applies both the immutable attempt update and the current job snapshot
    update within the active transaction.
    """
    attempt = repo.get_attempt(db, job_id=job.id, attempt_no=attempt_no)
    if attempt is None:
        raise AttemptInvariantViolation(
            f"Missing attempt row job_id={job.id} attempt_no={attempt_no}"
        )

    repo.update_attempt(
        db,
        attempt=attempt,
        status=attempt_status,
        error=error,
        finished_at=finished_at,
    )

    job.status = job_status
    job.last_error = error
    if result is not None:
        job.result = result
    repo.save(db, job)
