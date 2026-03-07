"""
Port definitions for the jobs domain.

Defines callable contracts used by other domains to interact with
job submission without depending on concrete service implementations.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from .models import Job


class JobSubmitter(Protocol):
    """Callable contract for submitting background jobs."""

    def __call__(
        self,
        db: Session,
        *,
        job_type: str,
        payload: dict,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> Job: ...
