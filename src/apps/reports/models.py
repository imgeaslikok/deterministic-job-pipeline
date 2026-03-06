import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

from .enums import ReportStatus


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    status: Mapped[str] = mapped_column(
        Enum(ReportStatus, name="report_status"),
        index=True,
        default=ReportStatus.pending,
    )

    job_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
