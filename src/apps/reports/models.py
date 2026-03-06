"""
SQLAlchemy model for reports.
"""

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.mixins import IdMixin, TimestampMixin
from src.db.types import enum_value_type

from .enums import ReportStatus


class Report(IdMixin, TimestampMixin, Base):
    """Database model representing a report."""

    __tablename__ = "reports"

    status: Mapped[str] = mapped_column(
        enum_value_type(ReportStatus, name="report_status"),
        index=True,
        default=ReportStatus.PENDING,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
