"""
Pydantic schemas for the reports API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.apps.reports.enums import ReportStatus


class ReportCreateRequest(BaseModel):
    """
    Request payload for creating a report.
    """

    model_config = ConfigDict(extra="forbid")
    # Empty body is allowed: {}


class ReportResponse(BaseModel):
    """
    API response model representing a report.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    status: ReportStatus
    job_id: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
