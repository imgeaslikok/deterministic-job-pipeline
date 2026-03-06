"""
Shared structured logging helpers.
"""

from __future__ import annotations

from typing import Any


def build_log_extra(**fields: Any) -> dict[str, Any]:
    """Return structured log fields without null values."""
    return {key: value for key, value in fields.items() if value is not None}
