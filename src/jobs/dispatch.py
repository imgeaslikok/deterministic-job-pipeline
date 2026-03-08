"""
Job dispatch helpers.

Responsible for sending jobs to the background worker.
"""

from __future__ import annotations

import threading
from typing import Protocol

from src.core.context import REQUEST_ID_HEADER
from src.core.enums import JobDispatchMode

from .tasks import process_job


class JobDispatcher(Protocol):
    def dispatch(self, *, job_id: str, request_id: str | None) -> None: ...


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


_DISPATCHER: JobDispatcher | None = None
_DISPATCHER_LOCK = threading.Lock()


def _build_dispatcher() -> JobDispatcher:
    """
    Return the dispatcher implementation for the current runtime environment.
    """
    from src.config.settings import settings

    if settings.job_dispatcher == JobDispatchMode.NOOP.value:
        return NoopJobDispatcher()
    return CeleryJobDispatcher()


def get_dispatcher() -> JobDispatcher:
    """
    Return the singleton job dispatcher for the current process.
    """
    global _DISPATCHER
    if _DISPATCHER is None:
        with _DISPATCHER_LOCK:
            if _DISPATCHER is None:
                _DISPATCHER = _build_dispatcher()
    return _DISPATCHER


def dispatch_job(job_id: str, request_id: str | None) -> None:
    """Dispatch a job using the configured dispatcher."""
    return get_dispatcher().dispatch(job_id=job_id, request_id=request_id)
