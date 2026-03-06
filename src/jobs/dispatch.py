"""
Job dispatch helpers.

Responsible for sending jobs to the background worker.
"""

from __future__ import annotations

from src.config.settings import settings
from src.core.context import REQUEST_ID_HEADER

from .tasks import process_job


class CeleryJobDispatcher:
    """Dispatch jobs through the Celery task queue."""

    def dispatch(self, *, job_id: str, request_id: str | None) -> None:
        process_job.apply_async(
            args=(job_id,),
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )


class NoopJobDispatcher:
    """Skip job dispatch while preserving the dispatcher interface."""

    def dispatch(self, *, job_id: str, request_id: str | None) -> None:
        return


def dispatch_job(job_id: str, request_id: str | None) -> None:
    """Dispatch a job using the configured dispatcher."""
    if settings.environment == "test":
        dispatcher = NoopJobDispatcher()
    else:
        dispatcher = CeleryJobDispatcher()

    dispatcher.dispatch(job_id=job_id, request_id=request_id)
