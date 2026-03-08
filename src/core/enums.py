"""
Core enum definitions.
"""

import enum


class LogLevel(str, enum.Enum):
    """Supported log levels used across the system."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class JobDispatchMode(str, enum.Enum):
    """"""

    CELERY = "celery"
    NOOP = "noop"
