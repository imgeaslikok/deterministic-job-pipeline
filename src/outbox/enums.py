"""
Outbox status definitions.
"""

from enum import Enum


class OutboxStatus(str, Enum):
    """Possible states of an outbox event."""

    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
