"""
SQLAlchemy models for jobs and job attempts.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.utils import now_utc
from src.db.base import Base
from src.db.mixins import IdMixin, TimestampMixin
from src.db.types import enum_value_type

from .enums import AttemptStatus, JobStatus


class Job(IdMixin, TimestampMixin, Base):
    """Current job state (latest snapshot)."""

    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_value_type(JobStatus, name="job_status"),
        index=True,
        default=JobStatus.PENDING,
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempts_history: Mapped[list["JobAttempt"]] = relationship(
        "JobAttempt",
        back_populates="job",
        order_by="JobAttempt.attempt_no",
        cascade="all, delete-orphan",
    )


class JobAttempt(IdMixin, Base):
    """Immutable attempt log entry for a job execution."""

    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no", name="uq_job_attempt_jobid_attemptno"),
        Index("ix_job_attempt_jobid_attemptno", "job_id", "attempt_no"),
    )

    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
    )

    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        enum_value_type(AttemptStatus, name="attempt_status"),
        index=True,
        default=AttemptStatus.RUNNING,
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
    )

    job: Mapped["Job"] = relationship("Job", back_populates="attempts_history")
