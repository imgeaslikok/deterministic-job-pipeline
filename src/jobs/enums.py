"""
Job lifecycle and event enums.
"""

import enum


class JobStatus(str, enum.Enum):
    """Possible lifecycle states of a job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    DEAD = "dead"


class AttemptStatus(str, enum.Enum):
    """Execution status of a job attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobEvent(str, enum.Enum):
    """Structured events emitted during job execution."""

    ATTEMPT_BEGIN = "job_attempt_begin"
    ATTEMPT_NOOP = "job_attempt_noop"
    ATTEMPT_SUCCEEDED = "job_attempt_succeeded"
    RETRY_NEEDED = "job_retry_needed"
    RETRY_SCHEDULED = "job_retry_scheduled"
    RETRY_EAGER_SIMULATED = "job_retry_eager_simulated"
    MOVED_TO_DLQ = "job_moved_to_dlq"
    FINALIZE_FAILED = "job_finalize_failed"
