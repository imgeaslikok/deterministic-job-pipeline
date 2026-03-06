"""
API exception mappings (Domain → HTTP).

Converts reports domain exceptions into consistent HTTP responses.
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.common.responses import error_response
from src.apps.reports.exceptions import (
    InvalidReportState,
    ReportJobAlreadyAttached,
    ReportNotFound,
)


async def _report_not_found(_: Request, exc: ReportNotFound) -> JSONResponse:
    return error_response(
        HTTPStatus.NOT_FOUND,
        detail="Report not found",
        report_id=exc.report_id,
    )


async def _invalid_report_state(_: Request, exc: InvalidReportState) -> JSONResponse:
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Invalid report state",
        report_id=exc.report_id,
        status=exc.status,
    )


async def _report_job_already_attached(
    _: Request, exc: ReportJobAlreadyAttached
) -> JSONResponse:
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Report already has a different job attached",
        report_id=exc.report_id,
        existing_job_id=exc.existing_job_id,
        new_job_id=exc.new_job_id,
    )


def register(app: FastAPI) -> None:
    """Register reports domain exception handlers."""
    app.add_exception_handler(ReportNotFound, _report_not_found)
    app.add_exception_handler(InvalidReportState, _invalid_report_state)
    app.add_exception_handler(ReportJobAlreadyAttached, _report_job_already_attached)