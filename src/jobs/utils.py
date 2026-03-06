from __future__ import annotations


def is_eager(celery_app) -> bool:
    """
    True if Celery eager mode is enabled (task_always_eager).

    We detect via the configured celery app.
    """
    try:
        return bool(getattr(celery_app.conf, "task_always_eager", False))
    except Exception:
        return False


def retry_countdown(current_retries: int) -> int:
    # simple exponential backoff with cap
    base = 2
    countdown = base ** max(current_retries, 0)
    return min(int(countdown), 60)
