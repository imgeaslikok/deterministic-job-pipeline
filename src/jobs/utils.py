from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


@contextmanager
def tx(db) -> Iterator[Any]:
    """
    Transaction boundary helper.

    Ensures row locks (e.g. SELECT ... FOR UPDATE) are released promptly,
    which is required for deterministic eager retry simulation.
    """
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise
