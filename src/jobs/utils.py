"""
Utility helpers for job retry and execution behavior.
"""

from __future__ import annotations


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
