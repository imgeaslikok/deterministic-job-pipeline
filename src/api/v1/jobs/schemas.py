"""
Pydantic schemas for the jobs API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from src.jobs.models import JobStatus


class JobResponse(BaseModel):
    """API representation of a job."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: str
    attempts: int
    last_error: str | None = None
    result: dict[str, Any] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _status_to_str(cls, v: Any) -> str:
        """Convert JobStatus enum values to strings."""
        return v.value if isinstance(v, JobStatus) else str(v)


class JobAttemptResponse(BaseModel):
    """API representation of a job attempt."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    attempt_no: int
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    created_at: datetime
