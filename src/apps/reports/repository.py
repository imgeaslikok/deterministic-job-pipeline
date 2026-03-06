"""
Repository helpers for reports.
"""

from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Report

T = TypeVar("T")


def save(db: Session, obj: T) -> T:
    """Persist an object and flush the session."""
    db.add(obj)
    db.flush()
    return obj


def get(db: Session, *, id: str) -> Report | None:
    """Fetch a report by id."""
    return db.get(Report, id)


def get_for_update(db: Session, *, id: str) -> Report | None:
    """Fetch a report with a row-level lock."""
    stmt = select(Report).where(Report.id == id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def create(db: Session, *, report: Report) -> Report:
    """Create and persist a new report."""
    db.add(report)
    db.flush()
    db.refresh(report)
    return report
