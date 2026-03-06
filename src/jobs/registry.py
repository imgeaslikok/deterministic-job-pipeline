from __future__ import annotations

from typing import Dict

from .exceptions import DuplicateExecutorRegistration, ExecutorNotRegistered
from .types import Executor

_EXECUTORS: Dict[str, Executor] = {}


def register_executor(job_type: str):
    """
    Register an executor for a job type.

    Expected signature:
        (ctx: JobContext, payload: dict[str, Any]) -> ExecutionResult | None
    """

    def decorator(fn: Executor) -> Executor:
        if job_type in _EXECUTORS:
            raise DuplicateExecutorRegistration(job_type)
        _EXECUTORS[job_type] = fn
        return fn

    return decorator


def get_executor(job_type: str) -> Executor:
    try:
        return _EXECUTORS[job_type]
    except KeyError as e:
        raise ExecutorNotRegistered(job_type) from e


def clear_registry() -> None:
    """Testing helper."""
    _EXECUTORS.clear()


# Backwards-compat alias
register = register_executor
