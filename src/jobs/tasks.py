"""
Celery Beat tasks for the job pipeline.

Contains only the periodic task that drains the outbox.
The worker task (process_job) lives in worker.py to avoid
circular imports with dispatch.py.
"""

from __future__ import annotations

from src.config.celery import celery


@celery.task
def publish_job_dispatch_events() -> int:
    """
    Publish pending job dispatch events from the outbox.
    """

    from . import publish

    return publish.publish_outbox_job_dispatch_events()
