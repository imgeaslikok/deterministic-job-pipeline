"""
Common API response helpers.
"""

from http import HTTPStatus

from fastapi.responses import JSONResponse


def error_response(status: HTTPStatus, *, detail: str, **extra) -> JSONResponse:
    """
    Create a standard JSON error response.
    """
    return JSONResponse(
        status_code=status,
        content={"detail": detail, **extra},
    )
