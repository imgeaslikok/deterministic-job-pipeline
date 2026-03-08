"""
Core enum definitions.
"""

import enum


class Environment(str, enum.Enum):
    """Application runtime environment."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LogLevel(str, enum.Enum):
    """Supported log levels used across the system."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class JobDispatchMode(str, enum.Enum):
    """Runtime mode for dispatching jobs to the background worker."""

    CELERY = "celery"
    NOOP = "noop"
