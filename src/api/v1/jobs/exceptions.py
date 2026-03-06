"""
API exception mappings for the jobs domain.

Maps domain exceptions to HTTP responses used by the API layer.
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.common.responses import error_response
from src.jobs.exceptions import (
    IdempotencyKeyConflict,
    InvalidJobState,
    JobNotFound,
)


async def _job_not_found(_: Request, exc: JobNotFound) -> JSONResponse:
    """Handle JobNotFound exceptions."""
    return error_response(
        HTTPStatus.NOT_FOUND,
        detail="Job not found",
        job_id=exc.job_id,
    )


async def _invalid_job_state(_: Request, exc: InvalidJobState) -> JSONResponse:
    """Handle InvalidJobState exceptions."""
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Invalid job state",
        job_id=exc.job_id,
        status=exc.status,
    )


async def _idempotency_conflict(
    _: Request, exc: IdempotencyKeyConflict
) -> JSONResponse:
    """Handle IdempotencyKeyConflict exceptions."""
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Idempotency-Key was reused with different request parameters.",
        idempotency_key=exc.key,
    )


def register(app: FastAPI) -> None:
    """
    Register jobs exception handlers on the FastAPI app.
    """
    app.add_exception_handler(JobNotFound, _job_not_found)
    app.add_exception_handler(InvalidJobState, _invalid_job_state)
    app.add_exception_handler(IdempotencyKeyConflict, _idempotency_conflict)
