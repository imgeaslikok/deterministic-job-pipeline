"""
Core utility helpers.
"""

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)
