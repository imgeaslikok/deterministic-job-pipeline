"""
Celery worker task for job execution.

Contains the process_job task and all execution helpers.
Kept separate from tasks.py to prevent circular imports
with dispatch.py (which needs to import process_job).
"""

from __future__ import annotations

import logging
import traceback

from sqlalchemy.orm import Session

from src.config.celery import celery
from src.config.settings import settings
from src.core.context import REQUEST_ID_HEADER
from src.core.enums import LogLevel
from src.core.utils import now_utc
from src.db.session import SessionLocal
from src.db.unit_of_work import UnitOfWork

from . import pipeline
from .enums import AttemptStatus, JobEvent, JobStatus
from .exceptions import ExecutorNotRegistered, NonRetryableJobError, RetryableJobError
from .messages import DEFAULT_RETRY_ERROR_MESSAGE, dlq_max_retries_error
from .registry import get_executor
from .types import (
    AttemptOutcome,
    CeleryTaskContext,
    ExecutionResult,
    JobContext,
    _ErrorClassification,
)
from .utils import is_eager, load_executors, retry_countdown, task_log

load_executors()

logger = logging.getLogger(__name__)


def _classify_execution_error(
    exc: Exception,
    *,
    current_retries: int,
    max_retries: int,
) -> _ErrorClassification:
    """
    Classify a job execution error into a retry or DLQ outcome.
    """

    error = str(exc)

    if isinstance(exc, (ExecutorNotRegistered, NonRetryableJobError)):
        return _ErrorClassification(
            job_status=JobStatus.DEAD,
            event=JobEvent.MOVED_TO_DLQ,
            level=LogLevel.ERROR,
            error=error,
            need_retry=False,
        )

    if isinstance(exc, RetryableJobError):
        if current_retries >= max_retries:
            error = dlq_max_retries_error(error)
            return _ErrorClassification(
                job_status=JobStatus.DEAD,
                event=JobEvent.MOVED_TO_DLQ,
                level=LogLevel.ERROR,
                error=error,
                need_retry=False,
            )

        return _ErrorClassification(
            job_status=JobStatus.PENDING,
            event=JobEvent.RETRY_NEEDED,
            level=LogLevel.WARNING,
            error=error,
            need_retry=True,
        )

    raise exc


def _resolve_celery_context(task) -> CeleryTaskContext:
    """
    Extract retry and request metadata from the bound Celery task.
    """

    current_retries = int(getattr(task.request, "retries", 0))
    max_retries = int(getattr(task, "max_retries", settings.job_max_retries))
    headers = getattr(task.request, "headers", None) or {}
    request_id = headers.get(REQUEST_ID_HEADER)

    return CeleryTaskContext(
        current_retries=current_retries,
        max_retries=max_retries,
        request_id=request_id,
    )


def _safe_finalize_attempt(
    db: Session,
    *,
    job,
    attempt_no: int,
    attempt_status: AttemptStatus,
    job_status: JobStatus,
    error: str | None,
    result: dict | None,
) -> None:
    """
    Finalize a job attempt and log failures without swallowing them silently.
    """

    try:
        with db.begin_nested():
            pipeline.finalize_attempt(
                db,
                job=job,
                attempt_no=attempt_no,
                attempt_status=attempt_status,
                job_status=job_status,
                finished_at=now_utc(),
                error=error,
                result=result,
            )
    except Exception:
        logger.exception(
            "finalize_attempt failed — job may be stuck in RUNNING",
            extra={"job_id": job.id, "attempt_no": attempt_no},
        )


def _run_executor(
    uow: UnitOfWork,
    *,
    job,
    attempt_no: int,
    celery_ctx: CeleryTaskContext,
) -> AttemptOutcome:
    """
    Run the registered executor and return the structured attempt outcome.
    """

    attempt_status = AttemptStatus.FAILED
    job_status = JobStatus.DEAD
    error: str | None = None
    result: dict | None = None
    event = JobEvent.ATTEMPT_SUCCEEDED
    level = LogLevel.INFO
    need_retry = False
    retry_reason: str | None = None

    try:
        executor = get_executor(job.job_type)
        exec_result: ExecutionResult | None = executor(
            JobContext(
                uow=uow,
                job_id=job.id,
                attempt_no=attempt_no,
                request_id=celery_ctx.request_id,
            ),
            job.payload or {},
        )
        result = exec_result.result if exec_result else None
        attempt_status = AttemptStatus.SUCCEEDED
        job_status = JobStatus.COMPLETED

    except (
        ExecutorNotRegistered,
        NonRetryableJobError,
        RetryableJobError,
    ) as exc:
        classification = _classify_execution_error(
            exc,
            current_retries=celery_ctx.current_retries,
            max_retries=celery_ctx.max_retries,
        )
        job_status = classification.job_status
        event = classification.event
        level = classification.level
        error = classification.error
        need_retry = classification.need_retry
        if need_retry:
            retry_reason = error

    except Exception:
        error = traceback.format_exc()
        job_status = JobStatus.DEAD
        event = JobEvent.MOVED_TO_DLQ
        level = LogLevel.ERROR
        raise

    finally:
        _safe_finalize_attempt(
            uow.session,
            job=job,
            attempt_no=attempt_no,
            attempt_status=attempt_status,
            job_status=job_status,
            error=error,
            result=result,
        )

    return AttemptOutcome(
        event=event,
        level=level,
        detail=error,
        need_retry=need_retry,
        retry_reason=retry_reason,
        attempt_no=attempt_no,
    )


def _execute_job_attempt(
    db: Session,
    *,
    job_id: str,
    started_at,
    celery_ctx: CeleryTaskContext,
) -> AttemptOutcome:
    """
    Start a job attempt and execute it when the pipeline allows execution.
    """

    with UnitOfWork(db) as uow:
        begin = pipeline.begin_attempt(
            uow.session,
            job_id=job_id,
            started_at=started_at,
        )

        if not begin.should_run:
            return AttemptOutcome(
                event=JobEvent.ATTEMPT_NOOP,
                level=LogLevel.INFO,
                detail=begin.reason,
                need_retry=False,
                retry_reason=None,
                attempt_no=None,
            )

        job, attempt_no = begin.unwrap()

        return _run_executor(
            uow,
            job=job,
            attempt_no=attempt_no,
            celery_ctx=celery_ctx,
        )


def _schedule_retry(
    task,
    *,
    job_id: str,
    celery_ctx: CeleryTaskContext,
    outcome: AttemptOutcome,
) -> None:
    """
    Schedule a retry using eager simulation or normal Celery retry semantics.
    """

    if is_eager(celery_app=celery):
        task_log(
            task,
            LogLevel.WARNING,
            JobEvent.RETRY_EAGER_SIMULATED,
            job_id=job_id,
            attempt_no=outcome.attempt_no,
            request_id=celery_ctx.request_id,
            detail=outcome.retry_reason,
        )
        task.apply(
            args=(job_id,),
            throw=True,
            retries=celery_ctx.current_retries + 1,
        )
        return

    countdown = retry_countdown(celery_ctx.current_retries)
    task_log(
        task,
        LogLevel.WARNING,
        JobEvent.RETRY_SCHEDULED,
        job_id=job_id,
        attempt_no=outcome.attempt_no,
        retries=celery_ctx.current_retries,
        countdown=countdown,
        request_id=celery_ctx.request_id,
        detail=outcome.retry_reason,
    )
    raise task.retry(
        exc=Exception(outcome.retry_reason or DEFAULT_RETRY_ERROR_MESSAGE),
        countdown=countdown,
    )


@celery.task(
    bind=True,
    max_retries=settings.job_max_retries,
    default_retry_delay=settings.job_default_retry_delay,
)
def process_job(self, job_id: str) -> None:
    """
    Execute a single job attempt.

    Runs the registered executor, persists the attempt outcome,
    and schedules retries or DLQ transitions when required.
    """

    celery_ctx = _resolve_celery_context(self)

    with SessionLocal() as db:
        task_log(
            self,
            LogLevel.INFO,
            JobEvent.ATTEMPT_BEGIN,
            job_id=job_id,
            request_id=celery_ctx.request_id,
            retries=celery_ctx.current_retries,
        )

        outcome = _execute_job_attempt(
            db,
            job_id=job_id,
            started_at=now_utc(),
            celery_ctx=celery_ctx,
        )

    task_log(
        self,
        outcome.level,
        outcome.event,
        job_id=job_id,
        attempt_no=outcome.attempt_no,
        request_id=celery_ctx.request_id,
        detail=outcome.detail,
    )

    if not outcome.need_retry:
        return

    _schedule_retry(
        self,
        job_id=job_id,
        celery_ctx=celery_ctx,
        outcome=outcome,
    )
