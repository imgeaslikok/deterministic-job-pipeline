"""
Common error messages used by the job pipeline.
"""

from __future__ import annotations

DEFAULT_RETRY_ERROR_MESSAGE = "Transient error"


def dlq_max_retries_error(error: str) -> str:
    """Format the error message used when a job is moved to the DLQ."""
    return f"DLQ: {error} (max retries exceeded)"
