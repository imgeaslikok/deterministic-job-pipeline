from http import HTTPStatus

from fastapi.responses import JSONResponse


def error_response(status: HTTPStatus, *, detail: str, **extra) -> JSONResponse:
    """
    Standard API error response.

    Example response body:
    {
        "detail": "Report not found",
        "report_id": "..."
    }
    """
    return JSONResponse(
        status_code=status,
        content={"detail": detail, **extra},
    )
