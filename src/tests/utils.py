"""
Test utility helpers.
"""

import uuid


def generate_idempotency_key(prefix: str = "test") -> str:
    """
    Generate a unique idempotency key for tests.

    Example:
        generate_idempotency_key("report")
        -> "test:report:9f1c2c..."
    """
    return f"test:{prefix}:{uuid.uuid4().hex}"
