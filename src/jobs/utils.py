"""
Utility helpers for job retry and execution behavior.
"""

from __future__ import annotations

import logging as _logging
import random
from importlib import import_module

from src.config.settings import settings
from src.core.enums import LogLevel
from src.core.logging import build_log_extra

from .enums import JobEvent

_FALLBACK_LOGGER = _logging.getLogger("jobs.worker")


def load_executors() -> None:
    """
    Import executor modules so their decorators register handlers.
    """

    for module_path in settings.job_executors:
        import_module(module_path)


def is_eager(celery_app) -> bool:
    """
    Return True if Celery eager mode is enabled.
    """
    try:
        return bool(getattr(celery_app.conf, "task_always_eager", False))
    except Exception:
        return False


def retry_countdown(current_retries: int) -> int:
    """
    Compute retry delay (seconds) using exponential backoff with full jitter.

    With defaults (base=2, cap=60):
      retry 0 → [0, 1]s
      retry 1 → [0, 2]s
      retry 2 → [0, 4]s
      retry 3 → [0, 8]s
      retry 6+ → [0, 60]s (cap)

    Jitter prevents thundering herds when many jobs fail simultaneously.
    """
    base = settings.job_retry_backoff_base
    cap = settings.job_retry_backoff_cap_seconds
    max_delay = min(base ** max(current_retries, 0), cap)
    return random.randint(0, max_delay)


def task_log(task, level: LogLevel, event: JobEvent, **fields) -> None:
    """
    Emit structured job pipeline logs through the task logger.
    """

    logger = getattr(task, "logger", None) or _FALLBACK_LOGGER

    extra = build_log_extra(
        component="jobs.worker",
        event=event.value,
        **fields,
    )
    getattr(logger, level.value, logger.info)(event.value, extra=extra)
