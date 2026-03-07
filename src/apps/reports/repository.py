"""
Repository helpers for reports.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Report


def get(db: Session, *, id: str) -> Report | None:
    """Fetch a report by id."""
    return db.get(Report, id)


def get_by_idempotency_key(db: Session, *, key: str) -> Report | None:
    """Fetch a report by idempotency key."""
    stmt = select(Report).where(Report.idempotency_key == key)
    return db.execute(stmt).scalar_one_or_none()


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
