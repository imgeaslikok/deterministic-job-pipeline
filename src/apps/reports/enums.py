"""
Report status definitions.
"""

import enum


class ReportStatus(str, enum.Enum):
    """Possible states of a report."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
