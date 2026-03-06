from __future__ import annotations

from sqlalchemy.orm import Session

from src.jobs.utils import tx

from . import repository as repo
from .enums import ReportStatus
from .exceptions import (
    InvalidReportState,
    ReportJobAlreadyAttached,
    ReportNotFound,
)
from .job_types import REPORT_GENERATE
from .models import Report


def _create_report(db: Session) -> Report:
    """Create a report row only (does not enqueue jobs)."""
    with tx(db):
        report = Report(status=ReportStatus.pending)
        repo.create(db, report=report)
        return report


def _attach_job(db: Session, *, report_id: str, job_id: str) -> Report:
    """Attach a job to a report (idempotent if already attached to the same job)."""
    with tx(db):
        report = repo.get_for_update(db, id=report_id)
        if report is None:
            raise ReportNotFound(report_id)

        if report.job_id:
            if report.job_id == job_id:
                return report
            raise ReportJobAlreadyAttached(
                report_id, existing_job_id=report.job_id, new_job_id=job_id
            )

        report.job_id = job_id
        repo.save(db, report)
        return report


def get_report(db: Session, *, report_id: str) -> Report:
    report = repo.get(db, id=report_id)
    if report is None:
        raise ReportNotFound(report_id)
    return report


def create_report_and_enqueue(
    db: Session, *, idempotency_key: str | None, request_id: str | None
) -> Report:
    """Create a report and enqueue the corresponding job."""
    from src.jobs import service as jobs_service

    report = _create_report(db=db)

    job = jobs_service.submit_job(
        db=db,
        type=REPORT_GENERATE,
        payload={"report_id": report.id},
        idempotency_key=idempotency_key,
        request_id=request_id,
    )

    return _attach_job(db=db, report_id=report.id, job_id=job.id)


def complete_report(db: Session, *, report_id: str, result: dict) -> Report:
    """Mark a pending report as ready and persist the result."""
    with tx(db):
        report = repo.get_for_update(db, id=report_id)
        if report is None:
            raise ReportNotFound(report_id)

        if report.status != ReportStatus.pending:
            raise InvalidReportState(report_id, status=report.status.value)

        report.result = result
        report.status = ReportStatus.ready
        repo.save(db, report)
        return report
