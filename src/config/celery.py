"""
Celery application configuration.

Defines broker/backend and worker behavior.
"""

from celery import Celery

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
)

# Test mode: run tasks synchronously
if settings.environment == "test":
    celery.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
