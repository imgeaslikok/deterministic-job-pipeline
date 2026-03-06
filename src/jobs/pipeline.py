from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import repository as repo
from .enums import AttemptStatus, JobStatus
from .exceptions import AttemptInvariantViolation
from .types import AttemptResult


def _is_terminal(status: JobStatus) -> bool:
    return status in (JobStatus.COMPLETED, JobStatus.DEAD)


def begin_attempt(db: Session, *, job_id: str, started_at: datetime) -> AttemptResult:
    """
    Start a single attempt under a row lock.

    - Locks the job row (SELECT ... FOR UPDATE)
    - Allocates attempt_no from job.attempts + 1
    - Marks job as running and creates an attempt row

    Returns should_run=False for not_found / terminal / duplicate invocations.
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
    repo.save(db, job)

    try:
        repo.create_attempt(
            db,
            job_id=job.id,
            attempt_no=attempt_no,
            status=AttemptStatus.RUNNING,
            started_at=started_at,
        )
    except IntegrityError:
        # Concurrent duplicate invocation.
        return AttemptResult(False, "duplicate", job, None)

    return AttemptResult(True, None, job, attempt_no)


def finalize_attempt(
    db: Session,
    *,
    job_id: str,
    attempt_no: int,
    attempt_status: AttemptStatus,
    job_status: JobStatus,
    finished_at: datetime,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    """
    Finalize an attempt and update the job state.

    Must be called within the same transaction started by the worker.
    """
    job = repo.get_for_update(db, id=job_id)
    if not job or _is_terminal(job.status):
        return

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


def move_to_dead(db: Session, *, job_id: str, error: str) -> None:
    """Force a job into DLQ (dead)."""
    job = repo.get_for_update(db, id=job_id)
    if not job or _is_terminal(job.status):
        return
    job.status = JobStatus.DEAD
    job.last_error = error
    repo.save(db, job)
