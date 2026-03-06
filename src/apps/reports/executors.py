from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from src.jobs.exceptions import NonRetryableJobError, RetryableJobError
from src.jobs.registry import register
from src.jobs.types import ExecutionResult, JobContext

from .exceptions import ReportNotFound
from .job_types import REPORT_GENERATE
from .service import complete_report


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NonRetryableJobError(f"Missing/invalid '{key}' in payload")
    return value


def _build_result(*, report_id: str, ctx: JobContext) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "meta": {
            "attempt_no": ctx.attempt_no,
            "request_id": ctx.request_id,
        },
        "data": {
            "rows": 42,
            "preview": [{"col": "value"}],
        },
    }


@register(REPORT_GENERATE)
def generate_report(ctx: JobContext, payload: dict[str, Any]) -> ExecutionResult:
    """Generate a demo report and persist the result."""
    report_id = _require_str(payload, "report_id")
    result = _build_result(report_id=report_id, ctx=ctx)

    try:
        complete_report(ctx.db, report_id=report_id, result=result)

    except ReportNotFound as e:
        # Domain invariant violation -> do not retry.
        raise NonRetryableJobError(str(e)) from e

    except SQLAlchemyError as e:
        # Database/infrastructure failure -> retry.
        raise RetryableJobError("Failed to persist report result") from e

    return ExecutionResult(result=result)
