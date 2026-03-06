import pytest

from src.apps.reports.enums import ReportStatus
from src.apps.reports.exceptions import (
    InvalidReportState,
    ReportJobAlreadyAttached,
    ReportNotFound,
)
from src.apps.reports.service import (
    _attach_job,
    _create_report,
    complete_report,
)


def test_create_report_creates_pending_row(db_session, get_report):
    """Creating a report should persist a pending report with no job attached."""
    report = _create_report(db_session)
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.status == ReportStatus.pending
    assert report2.job_id is None


def test_attach_job_sets_job_id(db_session, get_report):
    """Attaching a job should set the job_id on the report."""
    report = _create_report(db_session)
    db_session.commit()

    _attach_job(db_session, report_id=report.id, job_id="job-123")
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.job_id == "job-123"


def test_attach_job_missing_report_raises(db_session):
    """Attaching a job to a missing report should raise ReportNotFound."""
    with pytest.raises(ReportNotFound):
        _attach_job(db_session, report_id="missing", job_id="job-1")


def test_attach_job_conflicting_job_raises(db_session):
    """Attaching a different job to the same report should raise ReportJobAlreadyAttached."""
    report = _create_report(db_session)
    db_session.commit()

    _attach_job(db_session, report_id=report.id, job_id="job-1")
    db_session.commit()

    with pytest.raises(ReportJobAlreadyAttached):
        _attach_job(db_session, report_id=report.id, job_id="job-2")


def test_complete_report_sets_ready_and_result(db_session, get_report):
    """Completing a report should mark it ready and persist the result payload."""
    report = _create_report(db_session)
    db_session.commit()

    result = {"url": "s3://bucket/x.pdf"}
    complete_report(db_session, report_id=report.id, result=result)
    db_session.commit()

    report2 = get_report(report.id)
    assert report2 is not None
    assert report2.status == ReportStatus.ready
    assert report2.result == result


def test_complete_report_invalid_state_raises(db_session):
    """Completing a report twice should raise InvalidReportState."""
    report = _create_report(db_session)
    db_session.commit()

    complete_report(db_session, report_id=report.id, result={"ok": True})
    db_session.commit()

    with pytest.raises(InvalidReportState):
        complete_report(db_session, report_id=report.id, result={"ok": True})


def test_complete_report_missing_report_raises(db_session):
    """Completing a missing report should raise ReportNotFound."""
    with pytest.raises(ReportNotFound):
        complete_report(db_session, report_id="missing", result={"ok": True})