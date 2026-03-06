import pytest

from src.jobs import repository as repo
from src.jobs.enums import JobStatus
from src.jobs.exceptions import (
    IdempotencyKeyConflict,
    NonRetryableJobError,
    RetryableJobError,
)
from src.jobs.registry import register
from src.jobs.service import submit_job
from src.jobs.tasks import process_job
from src.jobs.types import ExecutionResult
from src.tests.utils import generate_idempotency_key


def test_success_path_creates_attempt_and_completes(db_session, get_job):
    """A successful executor should complete the job and write a single attempt."""

    @register("demo.success")
    def exec_success(ctx, payload):
        return ExecutionResult(result={"ok": True})

    job = submit_job(
        db_session,
        type="demo.success",
        payload={"x": 1},
        idempotency_key=generate_idempotency_key("job-success"),
    )
    db_session.commit()  # worker task uses a separate session

    process_job.apply(args=(job.id,), throw=True)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.completed

    attempts = repo.list_attempts(db_session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1


def test_retryable_error_retries_and_eventually_completes(db_session, get_job):
    """Retryable errors should create multiple attempts and eventually complete."""
    state = {"n": 0}

    @register("demo.retry")
    def exec_retry(ctx, payload):
        state["n"] += 1
        if state["n"] == 1:
            raise RetryableJobError("transient")
        return ExecutionResult(result={"ok": True, "attempts": state["n"]})

    job = submit_job(
        db_session,
        type="demo.retry",
        payload={},
        idempotency_key=generate_idempotency_key("job-retry"),
    )
    db_session.commit()

    process_job.apply(args=(job.id,), throw=True)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.completed

    attempts = repo.list_attempts(db_session, job_id=job.id)
    assert len(attempts) == 2
    assert [a.attempt_no for a in attempts] == [1, 2]


def test_non_retryable_error_moves_to_dlq(db_session, get_job):
    """Non-retryable errors should move the job to dead and write one attempt."""

    @register("demo.dead")
    def exec_dead(ctx, payload):
        raise NonRetryableJobError("bad payload")

    job = submit_job(
        db_session,
        type="demo.dead",
        payload={},
        idempotency_key=generate_idempotency_key("job-dead"),
    )
    db_session.commit()

    process_job.apply(args=(job.id,), throw=True)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.dead

    attempts = repo.list_attempts(db_session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1


def test_idempotency_key_returns_existing_job_without_creating_new_one(db_session):
    """Same idempotency key + same request params should reuse the existing job row."""

    @register("demo.idem")
    def exec_ok(ctx, payload):
        return ExecutionResult(result={"ok": True})

    key = generate_idempotency_key("job-idem-same")

    job1 = submit_job(
        db_session,
        type="demo.idem",
        payload={"a": 1},
        idempotency_key=key,
    )

    job2 = submit_job(
        db_session,
        type="demo.idem",
        payload={"a": 1},
        idempotency_key=key,
    )

    assert job2.id == job1.id


def test_idempotency_key_conflict_raises(db_session):
    """Same idempotency key with different params should raise IdempotencyKeyConflict."""

    @register("demo.idem2")
    def exec_ok(ctx, payload):
        return ExecutionResult(result={"ok": True})

    key = generate_idempotency_key("job-idem-conflict")

    _ = submit_job(
        db_session,
        type="demo.idem2",
        payload={"a": 1},
        idempotency_key=key,
    )

    with pytest.raises(IdempotencyKeyConflict):
        _ = submit_job(
            db_session,
            type="demo.idem2",
            payload={"a": 2},
            idempotency_key=key,
        )


def test_missing_executor_moves_to_dlq_and_writes_attempt(db_session, get_job):
    job = submit_job(
        db_session,
        type="demo.missing-executor",
        payload={},
        idempotency_key=generate_idempotency_key("job-missing-exec"),
    )
    db_session.commit()

    process_job.apply(args=(job.id,), throw=True)

    job2 = get_job(job.id)
    assert job2 is not None
    assert job2.status == JobStatus.dead

    attempts = repo.list_attempts(db_session, job_id=job.id)
    assert len(attempts) == 1
    assert attempts[0].error is not None
    assert "No executor registered" in attempts[0].error
