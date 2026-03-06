"""
API exception mappings (Domain → HTTP).

Converts jobs domain exceptions into consistent HTTP responses.
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
    return error_response(
        HTTPStatus.NOT_FOUND,
        detail="Job not found",
        job_id=exc.job_id,
    )


async def _invalid_job_state(_: Request, exc: InvalidJobState) -> JSONResponse:
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Invalid job state",
        job_id=exc.job_id,
        status=exc.status,
    )


async def _idempotency_conflict(
    _: Request, exc: IdempotencyKeyConflict
) -> JSONResponse:
    return error_response(
        HTTPStatus.CONFLICT,
        detail="Idempotency-Key was reused with different request parameters.",
        idempotency_key=exc.key,
    )


def register(app: FastAPI) -> None:
    """Register jobs domain exception handlers."""
    app.add_exception_handler(JobNotFound, _job_not_found)
    app.add_exception_handler(InvalidJobState, _invalid_job_state)
    app.add_exception_handler(IdempotencyKeyConflict, _idempotency_conflict)
