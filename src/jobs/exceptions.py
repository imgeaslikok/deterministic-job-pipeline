"""
Job pipeline and execution exceptions.
"""

from __future__ import annotations

# Pipeline / API level exceptions


class JobError(Exception):
    """Base error for job pipeline."""


class JobNotFound(JobError):
    """Raised when a job cannot be found."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job not found: {job_id}")
        self.job_id = job_id


class InvalidJobState(JobError):
    """Raised when an operation is invalid for the job state."""

    def __init__(self, job_id: str, status: str) -> None:
        super().__init__(f"Invalid job state: job_id={job_id} status={status}")
        self.job_id = job_id
        self.status = status


class IdempotencyKeyConflict(JobError):
    """Raised when an idempotency key is reused with different parameters."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Idempotency key conflict: {key}")
        self.idempotency_key = key


class AttemptInvariantViolation(JobError):
    """Raised when attempt rows are missing or inconsistent."""


# Execution signalling exceptions


class JobExecutionError(Exception):
    """Base class for executor errors signalled to the pipeline."""


class ExecutorNotRegistered(JobExecutionError):
    """Raised when a job type has no registered executor."""

    def __init__(self, job_type: str):
        self.job_type = job_type
        super().__init__(f"No executor registered for job type: {job_type!r}")


class DuplicateExecutorRegistration(JobExecutionError):
    """Raised when registering an executor twice for the same job type."""

    def __init__(self, job_type: str) -> None:
        self.job_type = job_type
        super().__init__(f"Executor already registered for job type: {job_type!r}")


class RetryableJobError(JobExecutionError):
    """Transient failure: pipeline should retry until max_retries, then DLQ."""


class NonRetryableJobError(JobExecutionError):
    """Permanent failure: pipeline should DLQ immediately (no retries)."""
