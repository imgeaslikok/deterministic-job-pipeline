"""
Reusable SQLAlchemy model mixins.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.utils import now_utc

from .constants import UUID_STR_MAX_LENGTH


class IdMixin:
    """Adds a UUID primary key column."""

    id: Mapped[str] = mapped_column(
        String(UUID_STR_MAX_LENGTH), primary_key=True, default=lambda: str(uuid.uuid4())
    )


class TimestampMixin:
    """Adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )
