from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.apps.reports.models import Report
from src.apps.reports.service import create_report_and_enqueue
from src.jobs.models import Job
from src.jobs.service import submit_job
from src.jobs.tasks import process_job
from src.tests.utils import generate_idempotency_key


def create_job(
    db: Session,
    *,
    job_type: str,
    payload: dict[str, Any] | None = None,
    idempotency_prefix: str = "job",
    request_id: str | None = None,
) -> Job:
    """
    Create a job via jobs_service.submit_job and commit so other sessions can see it.
    In test env, submit_job will NOT enqueue automatically (by design).
    """
    job = submit_job(
        db,
        job_type=job_type,
        payload=payload or {},
        idempotency_key=generate_idempotency_key(idempotency_prefix),
        request_id=request_id,
    )
    db.commit()
    db.refresh(job)
    return job


def run_job(job_id: str) -> None:
    """
    Run the Celery worker task deterministically in tests.
    """
    process_job.apply(args=(job_id,), throw=True)


def create_report_with_job(
    db: Session,
    *,
    idempotency_prefix: str = "report",
    request_id: str | None = "req-test",
) -> Report:
    """
    Create report + attach job, commit, return report.
    In test env, job enqueue is skipped; use run_job(report.job_id).
    """
    report = create_report_and_enqueue(
        db,
        idempotency_key=generate_idempotency_key(idempotency_prefix),
        request_id=request_id,
    )
    db.commit()
    db.refresh(report)
    return report
