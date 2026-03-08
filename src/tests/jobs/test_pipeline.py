"""
Integration tests for the job execution pipeline.

Covers successful execution, retry behavior, DLQ handling,
idempotency semantics, executor registration, and the correctness
of new invariant/type guards introduced in the improvement plan.
"""

from unittest.mock import MagicMock

import pytest

from src.core.enums import LogLevel
from src.core.utils import now_utc
from src.jobs import pipeline, runner
from src.jobs import repository as repo
from src.jobs.enums import AttemptStatus, JobEvent, JobStatus
from src.jobs.exceptions import (
    AttemptInvariantViolation,
    DuplicateExecutorRegistration,
    IdempotencyKeyConflict,
    InvalidJobState,
    JobNotFound,
    NonRetryableJobError,
    RetryableJobError,
)
from src.jobs.registry import register
from src.jobs.service import retry_from_dlq, submit_job
from src.jobs.types import (
    AttemptResult,
    CeleryTaskContext,
    ExecutionResult,
    _ErrorClassification,
)
from src.tests.factories import run_job
from src.tests.utils import generate_idempotency_key


def test_success_path_creates_attempt_and_completes(uow, get_job):
    """A successful executor should complete the job and write a single attempt."""

    @register("demo.success")
    def exec_success(ctx, payload):
        return ExecutionResult(result={"ok": True})

    job = submit_job(
        uow,
        job_type="demo.success",
        payload={"x": 1},
        idempotency_key=generate_idempotency_key("job-success"),
    )
    uow.commit()  # worker task uses a separate session

    run_job(job_id=job.id)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.COMPLETED

    attempts = repo.list_attempts(uow.session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1


def test_retryable_error_retries_and_eventually_completes(uow, get_job):
    """Retryable errors should create multiple attempts and eventually complete."""
    state = {"n": 0}

    @register("demo.retry")
    def exec_retry(ctx, payload):
        state["n"] += 1
        if state["n"] == 1:
            raise RetryableJobError("transient")
        return ExecutionResult(result={"ok": True, "attempts": state["n"]})

    job = submit_job(
        uow,
        job_type="demo.retry",
        payload={},
        idempotency_key=generate_idempotency_key("job-retry"),
    )
    uow.commit()

    run_job(job_id=job.id)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.COMPLETED

    attempts = repo.list_attempts(uow.session, job_id=job.id)
    assert len(attempts) == 2
    assert [a.attempt_no for a in attempts] == [1, 2]


def test_non_retryable_error_moves_to_dlq(uow, get_job):
    """Non-retryable errors should move the job to dead and write one attempt."""

    @register("demo.dead")
    def exec_dead(ctx, payload):
        raise NonRetryableJobError("bad payload")

    job = submit_job(
        uow,
        job_type="demo.dead",
        payload={},
        idempotency_key=generate_idempotency_key("job-dead"),
    )
    uow.commit()

    run_job(job_id=job.id)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.DEAD

    attempts = repo.list_attempts(uow.session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1


def test_idempotency_key_returns_existing_job_without_creating_new_one(uow):
    """Same idempotency key + same request params should reuse the existing job row."""

    @register("demo.idem")
    def exec_ok(ctx, payload):
        return ExecutionResult(result={"ok": True})

    key = generate_idempotency_key("job-idem-same")

    job1 = submit_job(
        uow,
        job_type="demo.idem",
        payload={"a": 1},
        idempotency_key=key,
    )

    job2 = submit_job(
        uow,
        job_type="demo.idem",
        payload={"a": 1},
        idempotency_key=key,
    )

    assert job2.id == job1.id


def test_idempotency_key_conflict_raises(uow):
    """Same idempotency key with different params should raise IdempotencyKeyConflict."""

    @register("demo.idem2")
    def exec_ok(ctx, payload):
        return ExecutionResult(result={"ok": True})

    key = generate_idempotency_key("job-idem-conflict")

    _ = submit_job(
        uow,
        job_type="demo.idem2",
        payload={"a": 1},
        idempotency_key=key,
    )

    with pytest.raises(IdempotencyKeyConflict):
        _ = submit_job(
            uow,
            job_type="demo.idem2",
            payload={"a": 2},
            idempotency_key=key,
        )


def test_missing_executor_moves_to_dlq_and_writes_attempt(uow, get_job):
    """Missing executor should move the job to dead and record a failed attempt."""
    job = submit_job(
        uow,
        job_type="demo.missing-executor",
        payload={},
        idempotency_key=generate_idempotency_key("job-missing-exec"),
    )
    uow.commit()

    run_job(job_id=job.id)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.DEAD

    attempts = repo.list_attempts(uow.session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].error is not None
    assert "No executor registered" in attempts[0].error


def test_register_executor_raises_on_duplicate_job_type():
    """Registering the same job type twice should raise DuplicateExecutorRegistration."""

    @register("report.generate")
    def first(ctx, payload):
        return None

    with pytest.raises(DuplicateExecutorRegistration):

        @register("report.generate")
        def second(ctx, payload):
            return None


def test_attempt_result_unwrap_returns_job_and_attempt_no():
    """unwrap() on a populated AttemptResult returns the job and attempt number."""
    job = MagicMock()
    result = AttemptResult(should_run=True, reason=None, job=job, attempt_no=3)
    returned_job, returned_no = result.unwrap()
    assert returned_job is job
    assert returned_no == 3


def test_attempt_result_unwrap_raises_on_missing_fields():
    """unwrap() raises AttemptInvariantViolation when job or attempt_no is None."""
    result = AttemptResult(
        should_run=False, reason="terminal", job=None, attempt_no=None
    )
    with pytest.raises(AttemptInvariantViolation):
        result.unwrap()


def test_error_classification_fields_are_accessible_by_name():
    """_ErrorClassification fields should be accessible by name (not positional)."""
    cls = _ErrorClassification(
        job_status=JobStatus.DEAD,
        event=JobEvent.MOVED_TO_DLQ,
        level=LogLevel.ERROR,
        error="boom",
        need_retry=False,
    )
    assert cls.job_status == JobStatus.DEAD
    assert cls.need_retry is False
    assert cls.error == "boom"


def test_finalize_attempt_raises_when_attempt_row_missing(uow):
    """finalize_attempt should raise AttemptInvariantViolation for a bogus attempt_no."""
    job = submit_job(
        uow,
        job_type="demo.finalize-inv",
        payload={},
        idempotency_key=generate_idempotency_key("finalize-inv"),
    )
    uow.commit()

    begin = pipeline.begin_attempt(uow.session, job_id=job.id, started_at=now_utc())
    assert begin.should_run
    job_obj, _ = begin.unwrap()

    with pytest.raises(AttemptInvariantViolation):
        pipeline.finalize_attempt(
            uow.session,
            job=job_obj,
            attempt_no=999,
            attempt_status=AttemptStatus.SUCCEEDED,
            job_status=JobStatus.COMPLETED,
            finished_at=now_utc(),
        )


def test_retry_from_dlq_raises_job_not_found_for_unknown_id(uow):
    """retry_from_dlq should raise JobNotFound for a non-existent job id."""
    with pytest.raises(JobNotFound):
        retry_from_dlq(uow, id="nonexistent-00000000")


def test_retry_from_dlq_raises_when_job_not_dead(uow):
    """retry_from_dlq should raise InvalidJobState when job is not in DEAD status."""
    job = submit_job(
        uow,
        job_type="demo.retry-state",
        payload={},
        idempotency_key=generate_idempotency_key("retry-state"),
    )
    uow.commit()

    with pytest.raises(InvalidJobState):
        retry_from_dlq(uow, id=job.id)


def test_run_executor_emits_metrics_on_success(uow):
    """_run_executor should emit duration and attempts metrics on success."""

    @register("demo.metrics-success")
    def exec_success(ctx, payload):
        return ExecutionResult(result={"ok": True})

    job = submit_job(
        uow,
        job_type="demo.metrics-success",
        payload={"x": 1},
        idempotency_key=generate_idempotency_key("metrics-success"),
    )
    uow.commit()

    duration_metric = MagicMock()
    duration_labels = MagicMock(return_value=duration_metric)

    attempts_metric = MagicMock()
    attempts_labels = MagicMock(return_value=attempts_metric)

    original_duration_labels = runner.JOB_DURATION_SECONDS.labels
    original_attempts_labels = runner.JOB_ATTEMPTS_TOTAL.labels

    runner.JOB_DURATION_SECONDS.labels = duration_labels
    runner.JOB_ATTEMPTS_TOTAL.labels = attempts_labels

    try:
        outcome = runner._run_executor(
            uow,
            job=job,
            attempt_no=1,
            celery_ctx=CeleryTaskContext(
                current_retries=0,
                max_retries=3,
                request_id="req-metrics-success",
            ),
        )
    finally:
        runner.JOB_DURATION_SECONDS.labels = original_duration_labels
        runner.JOB_ATTEMPTS_TOTAL.labels = original_attempts_labels

    assert outcome.need_retry is False
    assert outcome.event == JobEvent.ATTEMPT_SUCCEEDED
    assert outcome.level == LogLevel.INFO

    duration_labels.assert_called_once_with(job_type="demo.metrics-success")
    duration_metric.observe.assert_called_once()

    attempts_labels.assert_called_once_with(
        job_type="demo.metrics-success",
        status=JobStatus.COMPLETED.value,
    )
    attempts_metric.inc.assert_called_once()


def test_run_executor_emits_metrics_on_retryable_error(uow):
    """_run_executor should emit duration and attempts metrics on retryable error."""

    @register("demo.metrics-retry")
    def exec_retry(ctx, payload):
        raise RetryableJobError("transient failure")

    job = submit_job(
        uow,
        job_type="demo.metrics-retry",
        payload={},
        idempotency_key=generate_idempotency_key("metrics-retry"),
    )
    uow.commit()

    begin = pipeline.begin_attempt(
        uow.session,
        job_id=job.id,
        started_at=now_utc(),
    )
    assert begin.should_run is True
    locked_job, attempt_no = begin.unwrap()

    duration_metric = MagicMock()
    duration_labels = MagicMock(return_value=duration_metric)

    attempts_metric = MagicMock()
    attempts_labels = MagicMock(return_value=attempts_metric)

    original_duration_labels = runner.JOB_DURATION_SECONDS.labels
    original_attempts_labels = runner.JOB_ATTEMPTS_TOTAL.labels

    runner.JOB_DURATION_SECONDS.labels = duration_labels
    runner.JOB_ATTEMPTS_TOTAL.labels = attempts_labels

    try:
        outcome = runner._run_executor(
            uow,
            job=locked_job,
            attempt_no=attempt_no,
            celery_ctx=CeleryTaskContext(
                current_retries=0,
                max_retries=3,
                request_id="req-metrics-retry",
            ),
        )
    finally:
        runner.JOB_DURATION_SECONDS.labels = original_duration_labels
        runner.JOB_ATTEMPTS_TOTAL.labels = original_attempts_labels

    assert outcome.need_retry is True
    assert outcome.event == JobEvent.RETRY_NEEDED
    assert outcome.level == LogLevel.WARNING

    duration_labels.assert_called_once_with(job_type="demo.metrics-retry")
    duration_metric.observe.assert_called_once()

    attempts_labels.assert_called_once_with(
        job_type="demo.metrics-retry",
        status=JobStatus.PENDING.value,
    )
    attempts_metric.inc.assert_called_once()
