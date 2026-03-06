from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from .models import Job


@dataclass(frozen=True)
class ExecutionResult:
    """Returned by an executor on success."""

    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobContext:
    """
    Context passed into executors.
    """

    db: Session
    job_id: str
    attempt_no: int
    request_id: Optional[str] = None


@dataclass(frozen=True)
class AttemptResult:
    should_run: bool
    reason: str | None
    job: Job | None
    attempt_no: int | None


Executor = Callable[[JobContext, dict[str, Any]], ExecutionResult | None]
