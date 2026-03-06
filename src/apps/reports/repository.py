from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Report


def create(db: Session, *, report: Report) -> Report:
    db.add(report)
    db.flush()
    db.refresh(report)
    return report


def get(db: Session, *, id: str) -> Report | None:
    return db.get(Report, id)


def get_for_update(db: Session, *, id: str) -> Report | None:
    stmt = select(Report).where(Report.id == id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def save(db: Session, report: Report) -> Report:
    db.add(report)
    db.flush()
    return report
