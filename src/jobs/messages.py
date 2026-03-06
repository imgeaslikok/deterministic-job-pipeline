from __future__ import annotations

DEFAULT_RETRY_ERROR_MESSAGE = "Transient error"


def dlq_max_retries_error(error: str) -> str:
    return f"DLQ: {error} (max retries exceeded)"
