"""
Job dispatch helpers.

Responsible for sending jobs to the background worker.
"""

from __future__ import annotations

from src.config.settings import settings
from src.core.context import REQUEST_ID_HEADER

from .tasks import process_job


def dispatch_job(job_id: str, request_id: str | None) -> None:
    """Dispatch a job for background processing."""

    if settings.environment == "test":
        return

    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    process_job.apply_async(args=(job_id,), headers=headers)
