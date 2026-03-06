from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.utils import tx

from . import repository as repo
from .enums import ReportStatus
from .exceptions import (
    InvalidReportState,
    ReportJobAlreadyAttached,
    ReportNotFound,
)
from .job_types import REPORT_GENERATE
from .models import Report


def _create_report_row(db: Session) -> Report:
    """Create and persist a report row in pending state."""

    report = Report(status=ReportStatus.PENDING)
    repo.create(db, report=report)
    return report


def _attach_job_to_report(db: Session, *, report_id: str, job_id: str) -> Report:
    """
    Attach a job to a report.

    Idempotent when the same job is already attached.
    Raises if a different job is already attached.
    """

    report = repo.get_for_update(db, id=report_id)
    if report is None:
        raise ReportNotFound(report_id)

    if report.job_id:
        if report.job_id == job_id:
            return report
        raise ReportJobAlreadyAttached(
            report_id=report_id,
            existing_job_id=report.job_id,
            new_job_id=job_id,
        )

    report.job_id = job_id
    repo.save(db, report)
    return report


def create_report(
    db: Session,
    *,
    idempotency_key: str | None,
    request_id: str | None,
) -> Report:
    """
    Create a report and start its background generation flow.

    Orchestration:
        1. create report row
        2. submit generation job
        3. attach job to report
    """

    from src.jobs import service as jobs_service

    with tx(db):
        report = _create_report_row(db)

    job = jobs_service.submit_job(
        db=db,
        job_type=REPORT_GENERATE,
        payload={"report_id": report.id},
        idempotency_key=idempotency_key,
        request_id=request_id,
    )

    with tx(db):
        return _attach_job_to_report(db, report_id=report.id, job_id=job.id)


def get_report(db: Session, *, report_id: str) -> Report:
    """Fetch a report by id."""

    report = repo.get(db, id=report_id)
    if report is None:
        raise ReportNotFound(report_id)
    return report


def complete_report(db: Session, *, report_id: str, result: dict) -> Report:
    """Mark a pending report as ready and persist its result."""

    with tx(db):
        report = repo.get_for_update(db, id=report_id)
        if report is None:
            raise ReportNotFound(report_id)

        if report.status != ReportStatus.PENDING:
            raise InvalidReportState(report_id, status=report.status.value)

        report.result = result
        report.status = ReportStatus.READY
        repo.save(db, report)
        return report
