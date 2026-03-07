"""
Jobs API endpoints.

Provides inspection and operational controls for background jobs.
"""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from src.core.context import REQUEST_ID_HEADER
from src.db.session import get_db, get_uow
from src.db.unit_of_work import UnitOfWork
from src.jobs import service as jobs_service

from .schemas import JobAttemptResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/dlq", response_model=list[JobResponse])
def list_dlq(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    """List DLQ (dead) jobs."""
    return [
        JobResponse.model_validate(j) for j in jobs_service.list_dlq(db=db, limit=limit)
    ]


@router.get("/{id}", response_model=JobResponse)
def get_job(id: str, db: Session = Depends(get_db)) -> JobResponse:
    """Fetch a job by id."""
    job = jobs_service.get_job(db=db, id=id)
    return JobResponse.model_validate(job)


@router.post("/{id}/retry", response_model=JobResponse)
def retry_job(
    id: str,
    request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
    uow: UnitOfWork = Depends(get_uow),
) -> JobResponse:
    """Retry a DLQ job by resetting its state and re-enqueueing."""
    job = jobs_service.retry_from_dlq(uow=uow, id=id, request_id=request_id)
    return JobResponse.model_validate(job)


@router.get("/{id}/attempts", response_model=list[JobAttemptResponse])
def get_attempts(id: str, db: Session = Depends(get_db)) -> list[JobAttemptResponse]:
    """Return attempt audit trail for a job."""
    attempts = jobs_service.list_attempts(db=db, job_id=id)
    return [JobAttemptResponse.model_validate(a) for a in attempts]
