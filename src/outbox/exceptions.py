"""
Transactional outbox exceptions.
"""

from __future__ import annotations


class OutboxError(Exception):
    """Base error for transactional outbox operations."""


class OutboxEventNotFound(OutboxError):
    """Raised when an outbox event cannot be found."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Outbox event not found: {event_id}")
        self.event_id = event_id


class UnsupportedOutboxEventType(OutboxError):
    """Raised when an outbox event type cannot be published."""

    def __init__(self, event_type: str) -> None:
        super().__init__(f"Unsupported outbox event type: {event_type!r}")
        self.event_type = event_type
