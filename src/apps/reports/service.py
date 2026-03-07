"""
Application service for the reports domain.

Handles report lifecycle orchestration and integrates with the jobs system.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.repository import save
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


def _create_report_row(
    db: Session,
    *,
    idempotency_key: str | None,
) -> Report:
    """
    Create and persist a new report in pending state.
    """
    report = Report(
        status=ReportStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    return repo.create(db, report=report)


def _attach_job_to_report(db: Session, *, report_id: str, job_id: str) -> Report:
    """
    Attach a job to a report.

    Idempotent if the same job is already attached.
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
    save(db, report)
    return report


def create_report(
    db: Session,
    *,
    idempotency_key: str | None,
    request_id: str | None,
) -> Report:
    """
    Create a report and submit its generation job.
    """

    from src.jobs import service as jobs_service

    with tx(db):
        if idempotency_key:
            existing = repo.get_by_idempotency_key(db, key=idempotency_key)
            if existing is not None:
                return existing

        report = _create_report_row(db, idempotency_key=idempotency_key)

        job = jobs_service.submit_job(
            db=db,
            job_type=REPORT_GENERATE,
            payload={"report_id": report.id},
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        return _attach_job_to_report(db, report_id=report.id, job_id=job.id)


def get_report(db: Session, *, report_id: str) -> Report:
    """Fetch a report by id."""
    report = repo.get(db, id=report_id)
    if report is None:
        raise ReportNotFound(report_id)
    return report


def complete_report(db: Session, *, report_id: str, result: dict) -> Report:
    """
    Mark a report as ready and persist its result.
    """
    with tx(db):
        report = repo.get_for_update(db, id=report_id)
        if report is None:
            raise ReportNotFound(report_id)

        if report.status != ReportStatus.PENDING:
            raise InvalidReportState(report_id, status=report.status.value)

        report.result = result
        report.status = ReportStatus.READY
        save(db, report)
        return report
