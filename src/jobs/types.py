"""
Core data types used by the job execution pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from src.db.unit_of_work import UnitOfWork

from .models import Job


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


Executor = Callable[[JobContext, dict[str, Any]], ExecutionResult | None]
