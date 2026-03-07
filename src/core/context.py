"""
Request-scoped context utilities.
"""

from __future__ import annotations

import contextvars

REQUEST_ID_HEADER = "x-request-id"


_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(request_id: str | None) -> None:
    """Store the request ID in the current context."""
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    """Return the request ID from the current context."""
    return _request_id_var.get()
