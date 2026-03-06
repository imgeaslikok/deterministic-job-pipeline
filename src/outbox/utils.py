"""
Utility helpers for outbox publishing behavior.
"""

from __future__ import annotations

import logging

from src.core.enums import LogLevel
from src.core.logging import build_log_extra

from .exceptions import UnsupportedOutboxEventType
from .models import OutboxEvent

logger = logging.getLogger("outbox.publisher")


def publisher_log(
    level: LogLevel,
    log_event: str,
    *,
    outbox_event: OutboxEvent | None = None,
    **fields,
) -> None:
    """
    Emit structured logs for the outbox publisher.
    """

    extra = build_log_extra(
        component="outbox.publisher",
        event=log_event,
        event_id=outbox_event.id if outbox_event else None,
        event_type=outbox_event.event_type if outbox_event else None,
        retry_count=outbox_event.retry_count if outbox_event else None,
        **fields,
    )
    getattr(logger, level.value, logger.info)(log_event, extra=extra)


def backoff_delay_seconds(retry_count: int) -> int:
    """
    Return the delay before the next publish attempt.
    """

    return 30 * retry_count


def is_terminal_publish_error(exc: Exception) -> bool:
    """
    Return whether a publish failure should not be retried.
    """

    return isinstance(exc, UnsupportedOutboxEventType)
