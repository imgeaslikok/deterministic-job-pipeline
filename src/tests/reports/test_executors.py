import pytest

from src.apps.reports.enums import ReportStatus
from src.jobs.enums import JobStatus
from src.jobs.types import JobContext
from src.jobs.exceptions import NonRetryableJobError
from src.tests.factories import create_report_with_job, run_job
from src.apps.reports.executors import generate_report


def test_report_generation_flow_completes_job_and_report(
    db_session,
    register_report_executors,
    get_job,
    get_report,
):
    """End-to-end: report.generate completes job and marks report ready."""
    report = create_report_with_job(db_session, idempotency_prefix="report-flow")
    assert report.job_id is not None

    run_job(report.job_id)

    job = get_job(report.job_id)
    assert job is not None
    assert job.status == JobStatus.completed

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.status == ReportStatus.ready
    assert report2.result is not None


def test_generate_report_missing_report_is_non_retryable(db_session):
    ctx = JobContext(db=db_session, job_id="j1", attempt_no=1, request_id=None)

    with pytest.raises(NonRetryableJobError):
        generate_report(ctx, {"report_id": "missing-id"})