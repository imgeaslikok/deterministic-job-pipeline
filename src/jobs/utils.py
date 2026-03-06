"""
Utility helpers for job retry and execution behavior.
"""

from __future__ import annotations

from importlib import import_module

from src.config.settings import settings
from src.core.enums import LogLevel
from src.core.logging import build_log_extra

from .enums import JobEvent


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
    Compute retry delay using exponential backoff.
    """
    # simple exponential backoff with cap
    base = 2
    countdown = base ** max(current_retries, 0)
    return min(int(countdown), 60)


def task_log(task, level: LogLevel, event: JobEvent, **fields) -> None:
    """
    Emit structured job pipeline logs through the task logger.
    """

    logger = getattr(task, "logger", None)
    if not logger:
        return

    extra = build_log_extra(
        component="jobs.worker",
        event=event.value,
        **fields,
    )
    getattr(logger, level.value, logger.info)(event.value, extra=extra)
