"""
Celery application configuration.

Defines broker/backend, worker behavior, and periodic schedules.
"""

from celery import Celery

from src.core.enums import Environment

from .settings import settings

celery = Celery(
    "app",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.jobs.tasks"],
)

# Worker reliability settings
celery.conf.update(
    task_acks_late=True,  # acknowledge after task execution
    worker_prefetch_multiplier=1,  # avoid task hoarding per worker
    beat_schedule={
        "publish-job-dispatch-events": {
            "task": "src.jobs.tasks.publish_job_dispatch_events",
            "schedule": settings.outbox_publish_interval_seconds,
        },
        "reset-stuck-running-jobs": {
            "task": "src.jobs.tasks.reset_stuck_running_jobs",
            "schedule": settings.stuck_job_sweep_interval_seconds,
        },
    },
)

# Test mode: run tasks synchronously
if settings.environment == Environment.TEST:
    celery.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
