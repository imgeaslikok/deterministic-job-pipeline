"""
Pydantic schemas for the jobs API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.jobs.enums import AttemptStatus, JobStatus


class JobResponse(BaseModel):
    """API representation of a job."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: JobStatus
    attempts: int
    last_error: str | None = None
    result: dict[str, Any] | None = None


class JobAttemptResponse(BaseModel):
    """API representation of a job attempt."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    attempt_no: int
    status: AttemptStatus
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    created_at: datetime
