from __future__ import annotations

from importlib import import_module
from typing import Optional

from src.config.celery import celery
from src.config.settings import settings
from src.core.context import REQUEST_ID_HEADER
from src.core.enums import LogLevel
from src.core.utils import now_utc
from src.db.session import SessionLocal
from src.db.utils import tx

from . import pipeline
from .enums import AttemptStatus, JobEvent, JobStatus
from .exceptions import ExecutorNotRegistered, NonRetryableJobError, RetryableJobError
from .registry import get_executor
from .types import ExecutionResult, JobContext
from .utils import is_eager, retry_countdown


def _load_executors() -> None:
    """Import executor modules so their decorators register handlers (worker-only)."""
    for module_path in settings.job_executors:
        import_module(module_path)


_load_executors()


def _task_log(task, level: str, event: JobEvent, **fields) -> None:
    """Best-effort logging hook."""
    try:
        logger = getattr(task, "logger", None)
        msg = f"[jobs] {event.value} " + " ".join(
            f"{k}={v}" for k, v in fields.items() if v is not None
        )
        if logger:
            getattr(logger, level, logger.info)(msg)
        else:
            print(msg)
    except Exception:
        pass


@celery.task(bind=True, max_retries=3, default_retry_delay=2)
def process_job(self, job_id: str) -> None:
    """Run a single job attempt; persist outcome and schedule retry/DLQ."""
    current_retries = int(getattr(self.request, "retries", 0))
    max_retries = int(getattr(self, "max_retries", 3))

    request_id: Optional[str]
    try:
        request_id = getattr(self.request, "headers", {}).get(REQUEST_ID_HEADER)  # type: ignore[assignment]
    except Exception:
        request_id = None

    db = SessionLocal()
    try:
        _task_log(
            self, "info", JobEvent.ATTEMPT_BEGIN, job_id=job_id, retries=current_retries
        )

        started_at = now_utc()

        need_retry = False
        retry_reason: str | None = None
        attempt_no: int | None = None
        event: JobEvent = JobEvent.ATTEMPT_SUCCEEDED
        level: str = LogLevel.INFO
        detail: str | None = None

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
                    db=db, job_id=job_id, attempt_no=attempt_no, request_id=request_id
                )

                attempt_status: AttemptStatus
                job_status: JobStatus
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

                except ExecutorNotRegistered as e:
                    error = str(e)
                    attempt_status = AttemptStatus.FAILED
                    job_status = JobStatus.DEAD
                    event, level, detail = JobEvent.MOVED_TO_DLQ, LogLevel.ERROR, error

                except NonRetryableJobError as e:
                    error = str(e)
                    attempt_status = AttemptStatus.FAILED
                    job_status = JobStatus.DEAD
                    event, level, detail = JobEvent.MOVED_TO_DLQ, LogLevel.ERROR, error

                except RetryableJobError as e:
                    error = str(e)
                    attempt_status = AttemptStatus.FAILED
                    job_status = JobStatus.PENDING

                    if current_retries >= max_retries:
                        pipeline.move_to_dead(
                            db,
                            job_id=job_id,
                            error=f"DLQ: {error} (max retries exceeded)",
                        )
                        job_status = JobStatus.DEAD
                        event, level, detail = (
                            JobEvent.MOVED_TO_DLQ,
                            LogLevel.ERROR,
                            error,
                        )
                    else:
                        need_retry = True
                        retry_reason = error
                        event, level, detail = (
                            JobEvent.RETRY_NEEDED,
                            LogLevel.WARNING,
                            error,
                        )

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

        _task_log(
            self, level, event, job_id=job_id, attempt_no=attempt_no, detail=detail
        )

        if not need_retry:
            return

        if is_eager(celery_app=celery):
            _task_log(
                self,
                LogLevel.WARNING,
                JobEvent.RETRY_EAGER_SIMULATED,
                job_id=job_id,
                attempt_no=attempt_no,
                detail=retry_reason,
            )
            return self.apply(args=(job_id,), throw=True, retries=current_retries + 1)

        countdown = retry_countdown(current_retries)
        _task_log(
            self,
            LogLevel.WARNING,
            JobEvent.RETRY_SCHEDULED,
            job_id=job_id,
            attempt_no=attempt_no,
            retries=current_retries,
            countdown=countdown,
            detail=retry_reason,
        )
        raise self.retry(
            exc=Exception(retry_reason or "Transient error"), countdown=countdown
        )

    finally:
        db.close()
