from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Callable, Iterable

from fastapi import FastAPI


def _iter_submodules(package: ModuleType) -> Iterable[str]:
    """
    Yields fully-qualified module names under a given package.
    Example: "src.api.v1.jobs", "src.api.v1.reports", ...
    """
    prefix = package.__name__ + "."
    for m in pkgutil.iter_modules(package.__path__, prefix=prefix):
        yield m.name


def register_versioned_exception_handlers(
    app: FastAPI, *, version_package: str
) -> None:
    """
    Auto-discovers modules under `version_package` and calls `<module>.exceptions.register(app)`
    if present.

    version_package example: "src.api.v1"
    """
    v_pkg = importlib.import_module(version_package)

    for submodule_name in _iter_submodules(v_pkg):
        # We only care about "<domain>.exceptions"
        exceptions_module_name = f"{submodule_name}.exceptions"

        try:
            exc_mod = importlib.import_module(exceptions_module_name)
        except ModuleNotFoundError:
            # This domain package has no exceptions.py; that's fine.
            continue

        register_fn: Callable[[FastAPI], None] | None = getattr(
            exc_mod, "register", None
        )
        if callable(register_fn):
            register_fn(app)
