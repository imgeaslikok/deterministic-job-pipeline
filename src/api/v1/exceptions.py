"""
Register API-wide exception handlers.

Delegates to versioned modules (v1, v2, etc.).
"""

from fastapi import FastAPI

from src.api.common.exception_registry import register_versioned_exception_handlers


def register_exception_handlers(app: FastAPI) -> None:
    register_versioned_exception_handlers(app, version_package="src.api.v1")
