"""
SQLAlchemy model for reports.
"""

from sqlalchemy import JSON, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.constants import IDEMPOTENCY_KEY_MAX_LENGTH, UUID_STR_MAX_LENGTH
from src.db.mixins import IdMixin, TimestampMixin
from src.db.types import enum_value_type

from .enums import ReportStatus


class Report(IdMixin, TimestampMixin, Base):
    """Database model representing a report."""

    __tablename__ = "reports"
    __table_args__ = (
        Index(
            "uq_reports_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(IDEMPOTENCY_KEY_MAX_LENGTH),
        nullable=True,
    )
    status: Mapped[ReportStatus] = mapped_column(
        enum_value_type(ReportStatus, name="report_status"),
        index=True,
        default=ReportStatus.PENDING,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(UUID_STR_MAX_LENGTH), nullable=True, index=True
    )
    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
