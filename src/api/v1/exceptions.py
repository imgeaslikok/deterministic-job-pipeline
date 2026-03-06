"""
Register API exception handlers.

Delegates handler registration to versioned API modules (e.g. v1).
"""

from fastapi import FastAPI

from src.api.common.exception_registry import register_versioned_exception_handlers


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers for the API.
    """
    register_versioned_exception_handlers(app, version_package="src.api.v1")
