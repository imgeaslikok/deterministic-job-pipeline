"""
Core data types used by the job execution pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from src.core.enums import LogLevel
from src.db.unit_of_work import UnitOfWork

from .enums import JobEvent, JobStatus
from .exceptions import AttemptInvariantViolation
from .models import Job


@dataclass(frozen=True)
class CeleryTaskContext:
    """Context extracted from the active Celery task request."""

    current_retries: int
    max_retries: int
    request_id: str | None


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned by an executor on successful execution."""

    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobContext:
    """
    Execution context passed to job executors.

    uow — active transaction
    db  — alias for uow.session
    """

    uow: UnitOfWork
    job_id: str
    attempt_no: int
    request_id: Optional[str] = None

    @property
    def db(self) -> Session:
        """Backwards compatible alias."""
        return self.uow.session


@dataclass(frozen=True)
class AttemptResult:
    """Outcome of attempting to start a job execution."""

    should_run: bool
    reason: str | None
    job: Job | None
    attempt_no: int | None

    def unwrap(self) -> tuple[Job, int]:
        """Return job and attempt_no, raising if the attempt cannot run."""
        if self.job is None or self.attempt_no is None:
            raise AttemptInvariantViolation(
                f"AttemptResult.unwrap() called but fields are missing: reason={self.reason!r}"
            )
        return self.job, self.attempt_no


@dataclass(frozen=True)
class _ErrorClassification:
    """Structured result of classifying a job execution error."""

    job_status: JobStatus
    event: JobEvent
    level: LogLevel
    error: str
    need_retry: bool


@dataclass(frozen=True)
class AttemptOutcome:
    """Outcome of a completed job attempt."""

    event: JobEvent
    level: LogLevel
    detail: str | None
    need_retry: bool
    retry_reason: str | None
    attempt_no: int | None


Executor = Callable[[JobContext, dict[str, Any]], ExecutionResult | None]
