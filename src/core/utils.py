from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)
