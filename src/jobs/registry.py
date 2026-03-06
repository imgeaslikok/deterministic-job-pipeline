"""
Executor registry for job handlers.

Maps job types to their registered executor functions.
"""

from __future__ import annotations

from typing import Dict

from .exceptions import DuplicateExecutorRegistration, ExecutorNotRegistered
from .types import Executor

_EXECUTORS: Dict[str, Executor] = {}


def register_executor(job_type: str):
    """
    Register an executor for a job type.

    The executor must accept (ctx, payload) and return an ExecutionResult.
    """

    def decorator(fn: Executor) -> Executor:
        if job_type in _EXECUTORS:
            raise DuplicateExecutorRegistration(job_type)
        _EXECUTORS[job_type] = fn
        return fn

    return decorator


def get_executor(job_type: str) -> Executor:
    """Return the executor registered for a job type."""
    try:
        return _EXECUTORS[job_type]
    except KeyError as e:
        raise ExecutorNotRegistered(job_type) from e


def clear_registry() -> None:
    """Clear the executor registry (testing helper)."""
    _EXECUTORS.clear()


# Backwards-compat alias
register = register_executor
