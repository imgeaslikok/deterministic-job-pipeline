import enum

# lifecycle (domain state)


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    dead = "dead"


class AttemptStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


# observability (events)


class JobEvent(str, enum.Enum):
    attempt_begin = "job_attempt_begin"
    attempt_noop = "job_attempt_noop"
    attempt_succeeded = "job_attempt_succeeded"
    retry_needed = "job_retry_needed"
    retry_scheduled = "job_retry_scheduled"
    retry_eager_simulated = "job_retry_eager_simulated"
    moved_to_dlq = "job_moved_to_dlq"
