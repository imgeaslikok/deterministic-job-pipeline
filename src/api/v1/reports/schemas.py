from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Empty body is allowed: {}


class ReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    status: str
    job_id: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
