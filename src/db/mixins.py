from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(UTC)


class IdMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )
