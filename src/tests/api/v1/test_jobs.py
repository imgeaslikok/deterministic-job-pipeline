"""
API tests for job endpoints.

Covers job retrieval, attempt history inspection, DLQ listing,
and retrying jobs through the HTTP API.
"""

from http import HTTPStatus

from src.jobs.enums import JobStatus
from src.jobs.exceptions import NonRetryableJobError
from src.jobs.registry import register
from src.tests.factories import create_job, run_job


def test_get_job_returns_job(api_base, client, db_session):
    """GET /jobs/{id} should return job details for an existing job."""
    job_type = "demo.api.job.get"

    @register(job_type)
    def exec_ok(ctx, payload):
        return None

    job = create_job(
        db_session,
        job_type=job_type,
        payload={"x": 1},
        idempotency_prefix="api-job-get",
    )

    res = client.get(f"{api_base}/jobs/{job.id}")

    assert res.status_code == HTTPStatus.OK

    body = res.json()
    assert body["id"] == job.id
    assert body["job_type"] == job_type
    assert body["status"] == JobStatus.PENDING.value


def test_get_attempts_returns_attempt_audit_trail(
    api_base,
    client,
    db_session,
):
    """GET /jobs/{id}/attempts should return recorded attempts for a job."""
    job_type = "demo.api.job.attempts"

    @register(job_type)
    def exec_ok(ctx, payload):
        return None

    job = create_job(
        db_session,
        job_type=job_type,
        payload={},
        idempotency_prefix="api-job-attempts",
    )

    run_job(job.id)

    res = client.get(f"{api_base}/jobs/{job.id}/attempts")

    assert res.status_code == HTTPStatus.OK

    body = res.json()
    assert len(body) == 1
    assert body[0]["job_id"] == job.id
    assert body[0]["attempt_no"] == 1


def test_list_dlq_returns_dead_jobs(api_base, client, db_session):
    """GET /jobs/dlq should return jobs currently in dead state."""
    job_type = "demo.api.job.dlq"

    @register(job_type)
    def exec_dead(ctx, payload):
        raise NonRetryableJobError("bad payload")

    job = create_job(
        db_session,
        job_type=job_type,
        payload={},
        idempotency_prefix="api-job-dlq",
    )

    run_job(job.id)

    res = client.get(f"{api_base}/jobs/dlq")

    assert res.status_code == HTTPStatus.OK

    body = res.json()
    assert any(item["id"] == job.id for item in body)

    dlq_job = next(item for item in body if item["id"] == job.id)
    assert dlq_job["status"] == JobStatus.DEAD.value


def test_retry_job_resets_dead_job_to_pending(api_base, client, db_session, get_job):
    """POST /jobs/{id}/retry should reset a dead job back to pending."""
    job_type = "demo.api.job.retry"

    @register(job_type)
    def exec_dead(ctx, payload):
        raise NonRetryableJobError("bad payload")

    job = create_job(
        db_session,
        job_type=job_type,
        payload={},
        idempotency_prefix="api-job-retry",
    )

    run_job(job.id)

    dead_job = get_job(job.id)
    assert dead_job is not None
    assert dead_job.status == JobStatus.DEAD

    res = client.post(f"{api_base}/jobs/{job.id}/retry")

    assert res.status_code == HTTPStatus.OK

    body = res.json()
    assert body["id"] == job.id
    assert body["status"] == JobStatus.PENDING.value
