"""
Request ID middleware.

Ensures every request has a request identifier available in the
request context and response headers.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.context import REQUEST_ID_HEADER, set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Attach a request ID to each incoming request.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Generate or propagate the request ID for the current request.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        set_request_id(request_id)

        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
