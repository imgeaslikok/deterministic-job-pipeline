from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from src.apps.reports import service as reports_service
from src.db.session import get_db

from .schemas import ReportCreateRequest, ReportResponse

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    req: ReportCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request_id: str | None = Header(default=None, alias="X-Request-Id"),
    db: Session = Depends(get_db),
) -> ReportResponse:
    report = reports_service.create_report_and_enqueue(
        db=db,
        idempotency_key=idempotency_key,
        request_id=request_id,
    )
    return ReportResponse.model_validate(report)


@router.get("/{id}", response_model=ReportResponse)
def get_report(id: str, db: Session = Depends(get_db)) -> ReportResponse:
    """Fetch a report by id."""
    report = reports_service.get_report(db=db, report_id=id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportResponse.model_validate(report)
