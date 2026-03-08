"""
Celery tasks for the job pipeline.

Contains the periodic outbox publisher task and the
worker entrypoint for job execution.
"""

from __future__ import annotations

from src.config.celery import celery
from src.config.settings import settings

from .runner import run_process_job


@celery.task(
    bind=True,
    max_retries=settings.job_max_retries,
    default_retry_delay=settings.job_default_retry_delay,
)
def process_job(self, job_id: str) -> None:
    """
    Execute a single job attempt.

    Runs the registered executor, persists the attempt outcome,
    and schedules retries or DLQ transitions when required.
    """

    return run_process_job(self, job_id=job_id)


@celery.task
def publish_job_dispatch_events() -> int:
    """
    Publish pending job dispatch events from the outbox.
    """

    from . import publish

    return publish.publish_outbox_job_dispatch_events()
