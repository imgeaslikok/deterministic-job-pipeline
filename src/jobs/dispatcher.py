from __future__ import annotations

from typing import Protocol

from src.config.settings import settings
from src.core.context import REQUEST_ID_HEADER

from .tasks import process_job


class JobDispatcher(Protocol):
    def dispatch(self, *, job_id: str, request_id: str | None) -> None: ...


class CeleryJobDispatcher:
    def dispatch(self, *, job_id: str, request_id: str | None) -> None:
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        process_job.apply_async(args=(job_id,), headers=headers)


class NoopJobDispatcher:
    def dispatch(self, *, job_id: str, request_id: str | None) -> None:
        return


def get_job_dispatcher() -> JobDispatcher:
    if settings.environment == "test":
        return NoopJobDispatcher()
    return CeleryJobDispatcher()
