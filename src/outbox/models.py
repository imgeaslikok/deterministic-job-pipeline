"""
SQLAlchemy model for transactional outbox events.
"""

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.mixins import IdMixin, TimestampMixin
from src.db.types import enum_value_type

from .enums import OutboxStatus


class OutboxEvent(IdMixin, TimestampMixin, Base):
    """Transactional outbox event."""

    __tablename__ = "outbox_events"

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[OutboxStatus] = mapped_column(
        enum_value_type(OutboxStatus, name="outbox_status"),
        index=True,
        default=OutboxStatus.PENDING,
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
