"""
Common error messages used by the outbox publisher.
"""

from __future__ import annotations


def unsupported_event_type_error(event_type: str) -> str:
    """
    Format the error message used when an outbox event type
    is not supported by the publisher.
    """
    return f"Unsupported outbox event type: {event_type}"
