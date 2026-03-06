"""
Tests for reports domain service helpers.

Covers report creation, job attachment, and report completion logic.
"""

import pytest

from src.apps.reports.enums import ReportStatus
from src.apps.reports.exceptions import (
    InvalidReportState,
    ReportJobAlreadyAttached,
    ReportNotFound,
)
from src.apps.reports.models import Report
from src.apps.reports.service import (
    _attach_job_to_report,
    _create_report_row,
    complete_report,
    create_report,
)
from src.jobs.models import Job
from src.outbox.models import OutboxEvent
from src.tests.utils import generate_idempotency_key


def test_create_report_creates_pending_row(db_session, get_report):
    """Creating a report should persist a pending report with no job attached."""
    report = _create_report_row(db_session)
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.status == ReportStatus.PENDING
    assert report2.job_id is None


def test_attach_job_sets_job_id(db_session, get_report):
    """Attaching a job should set the job_id on the report."""
    report = _create_report_row(db_session)
    db_session.commit()

    _attach_job_to_report(db_session, report_id=report.id, job_id="job-123")
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.job_id == "job-123"


def test_attach_job_missing_report_raises(db_session):
    """Attaching a job to a missing report should raise ReportNotFound."""
    with pytest.raises(ReportNotFound):
        _attach_job_to_report(db_session, report_id="missing", job_id="job-1")


def test_attach_job_conflicting_job_raises(db_session):
    """Attaching a different job to the same report should raise ReportJobAlreadyAttached."""
    report = _create_report_row(db_session)
    db_session.commit()

    _attach_job_to_report(db_session, report_id=report.id, job_id="job-1")
    db_session.commit()

    with pytest.raises(ReportJobAlreadyAttached):
        _attach_job_to_report(db_session, report_id=report.id, job_id="job-2")


def test_create_report_rolls_back_when_job_attachment_fails(db_session, monkeypatch):
    """Creating a report should roll back report and job state when attachment fails."""
    original_attach = _attach_job_to_report

    reports_before = db_session.query(Report).count()
    jobs_before = db_session.query(Job).count()
    events_before = db_session.query(OutboxEvent).count()

    def failing_attach(db, *, report_id: str, job_id: str):
        original_attach(db, report_id=report_id, job_id=job_id)
        raise RuntimeError("attach failed")

    monkeypatch.setattr(
        "src.apps.reports.service._attach_job_to_report",
        failing_attach,
    )

    with pytest.raises(RuntimeError, match="attach failed"):
        create_report(
            db_session,
            idempotency_key=generate_idempotency_key("report-create-rollback"),
            request_id="req-rollback",
        )

    db_session.rollback()
    db_session.expire_all()

    reports_after = db_session.query(Report).count()
    jobs_after = db_session.query(Job).count()
    events_after = db_session.query(OutboxEvent).count()

    assert reports_after == reports_before
    assert jobs_after == jobs_before
    assert events_after == events_before


def test_complete_report_sets_ready_and_result(db_session, get_report):
    """Completing a report should mark it ready and persist the result payload."""
    report = _create_report_row(db_session)
    db_session.commit()

    result = {"url": "s3://bucket/x.pdf"}
    complete_report(db_session, report_id=report.id, result=result)
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.status == ReportStatus.READY
    assert report2.result == result


def test_complete_report_invalid_state_raises(db_session):
    """Completing a report twice should raise InvalidReportState."""
    report = _create_report_row(db_session)
    db_session.commit()

    complete_report(db_session, report_id=report.id, result={"ok": True})
    db_session.commit()

    with pytest.raises(InvalidReportState):
        complete_report(db_session, report_id=report.id, result={"ok": True})


def test_complete_report_missing_report_raises(db_session):
    """Completing a missing report should raise ReportNotFound."""
    with pytest.raises(ReportNotFound):
        complete_report(db_session, report_id="missing", result={"ok": True})
