"""
Helpers for registering version-scoped API exception handlers.

Discovers domain modules under a given API version and registers
their exception handlers if an ``exceptions.register(app)`` function exists.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Callable, Iterable

from fastapi import FastAPI


def _iter_submodules(package: ModuleType) -> Iterable[str]:
    """
    Yield fully qualified module names under a package.

    Used to discover domain modules within a versioned API package
    such as ``src.api.v1.jobs`` or ``src.api.v1.reports``.
    """
    prefix = package.__name__ + "."
    for m in pkgutil.iter_modules(package.__path__, prefix=prefix):
        yield m.name


def register_versioned_exception_handlers(
    app: FastAPI, *, version_package: str
) -> None:
    """
    Register exception handlers defined in versioned API modules.

    Each domain module may define an ``exceptions`` module exposing
    a ``register(app)`` function. If present, it is invoked to attach
    the handlers to the FastAPI application.
    """
    v_pkg = importlib.import_module(version_package)

    for submodule_name in _iter_submodules(v_pkg):
        exceptions_module_name = f"{submodule_name}.exceptions"

        try:
            exc_mod = importlib.import_module(exceptions_module_name)
        except ModuleNotFoundError:
            continue

        register_fn: Callable[[FastAPI], None] | None = getattr(
            exc_mod, "register", None
        )
        if callable(register_fn):
            register_fn(app)
