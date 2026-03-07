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


def get_job_dispatcher() -> CeleryJobDispatcher | NoopJobDispatcher:
    """
    Return the dispatcher implementation for the current runtime environment.
    """
    if settings.environment == "test":
        return NoopJobDispatcher()
    return CeleryJobDispatcher()


def dispatch_job(job_id: str, request_id: str | None) -> None:
    """Dispatch a job using the configured dispatcher."""
    dispatcher = get_job_dispatcher()
    dispatcher.dispatch(job_id=job_id, request_id=request_id)
