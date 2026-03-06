"""
Celery tasks for the job execution pipeline.

Defines the worker entrypoints responsible for running jobs and
publishing outbox dispatch events.
"""

from __future__ import annotations

from src.config.celery import celery
from src.core.context import REQUEST_ID_HEADER
from src.core.enums import LogLevel
from src.core.utils import now_utc
from src.db.session import SessionLocal
from src.db.utils import tx

from . import pipeline
from .enums import AttemptStatus, JobEvent, JobStatus
from .exceptions import ExecutorNotRegistered, NonRetryableJobError, RetryableJobError
from .messages import DEFAULT_RETRY_ERROR_MESSAGE, dlq_max_retries_error
from .registry import get_executor
from .types import ExecutionResult, JobContext
from .utils import is_eager, load_executors, retry_countdown, task_log

load_executors()


def _classify_execution_error(
    exc: Exception,
    *,
    current_retries: int,
    max_retries: int,
) -> tuple[JobStatus, JobEvent, LogLevel, str, bool]:
    """
    Classify a job execution error into a retry or DLQ outcome.
    """

    error = str(exc)

    if isinstance(exc, (ExecutorNotRegistered, NonRetryableJobError)):
        return JobStatus.DEAD, JobEvent.MOVED_TO_DLQ, LogLevel.ERROR, error, False

    if isinstance(exc, RetryableJobError):
        if current_retries >= max_retries:
            error = dlq_max_retries_error(error)
            return JobStatus.DEAD, JobEvent.MOVED_TO_DLQ, LogLevel.ERROR, error, False

        return JobStatus.PENDING, JobEvent.RETRY_NEEDED, LogLevel.WARNING, error, True

    raise exc


@celery.task(bind=True, max_retries=3, default_retry_delay=2)
def process_job(self, job_id: str) -> None:
    """
    Execute a single job attempt.

    Runs the registered executor, persists the attempt outcome,
    and schedules retries or DLQ transitions when required.
    """

    current_retries = int(getattr(self.request, "retries", 0))
    max_retries = int(getattr(self, "max_retries", 3))

    headers = getattr(self.request, "headers", None) or {}
    request_id = headers.get(REQUEST_ID_HEADER)

    with SessionLocal() as db:
        task_log(
            self,
            LogLevel.INFO,
            JobEvent.ATTEMPT_BEGIN,
            job_id=job_id,
            request_id=request_id,
            retries=current_retries,
        )

        started_at = now_utc()

        need_retry = False
        retry_reason: str | None = None
        attempt_no: int | None = None
        detail: str | None = None
        event: JobEvent = JobEvent.ATTEMPT_SUCCEEDED
        level: LogLevel = LogLevel.INFO

        with tx(db):
            begin = pipeline.begin_attempt(db, job_id=job_id, started_at=started_at)
            if not begin.should_run:
                event, level, detail = (
                    JobEvent.ATTEMPT_NOOP,
                    LogLevel.INFO,
                    begin.reason,
                )
            else:
                assert begin.job is not None and begin.attempt_no is not None
                job = begin.job
                attempt_no = begin.attempt_no

                ctx = JobContext(
                    db=db,
                    job_id=job_id,
                    attempt_no=attempt_no,
                    request_id=request_id,
                )

                attempt_status: AttemptStatus = AttemptStatus.FAILED
                job_status: JobStatus = JobStatus.DEAD
                error: str | None = None
                result: dict | None = None

                try:
                    executor = get_executor(job.job_type)
                    exec_result: ExecutionResult | None = executor(
                        ctx, job.payload or {}
                    )
                    result = exec_result.result if exec_result else None

                    attempt_status = AttemptStatus.SUCCEEDED
                    job_status = JobStatus.COMPLETED

                except (
                    ExecutorNotRegistered,
                    NonRetryableJobError,
                    RetryableJobError,
                ) as exc:
                    (
                        job_status,
                        event,
                        level,
                        error,
                        need_retry,
                    ) = _classify_execution_error(
                        exc,
                        current_retries=current_retries,
                        max_retries=max_retries,
                    )
                    detail = error
                    if need_retry:
                        retry_reason = error

                finally:
                    finished_at = now_utc()
                    pipeline.finalize_attempt(
                        db,
                        job_id=job_id,
                        attempt_no=attempt_no,
                        attempt_status=attempt_status,
                        job_status=job_status,
                        finished_at=finished_at,
                        error=error,
                        result=result,
                    )

        task_log(
            self,
            level,
            event,
            job_id=job_id,
            attempt_no=attempt_no,
            request_id=request_id,
            detail=detail,
        )

        if not need_retry:
            return

        if is_eager(celery_app=celery):
            task_log(
                self,
                LogLevel.WARNING,
                JobEvent.RETRY_EAGER_SIMULATED,
                job_id=job_id,
                attempt_no=attempt_no,
                request_id=request_id,
                detail=retry_reason,
            )
            return self.apply(args=(job_id,), throw=True, retries=current_retries + 1)

        countdown = retry_countdown(current_retries)
        task_log(
            self,
            LogLevel.WARNING,
            JobEvent.RETRY_SCHEDULED,
            job_id=job_id,
            attempt_no=attempt_no,
            retries=current_retries,
            countdown=countdown,
            request_id=request_id,
            detail=retry_reason,
        )
        raise self.retry(
            exc=Exception(retry_reason or DEFAULT_RETRY_ERROR_MESSAGE),
            countdown=countdown,
        )


@celery.task
def publish_job_dispatch_events() -> int:
    """
    Publish pending job dispatch events from the outbox.
    """

    from . import publish

    return publish.publish_outbox_job_dispatch_events()
