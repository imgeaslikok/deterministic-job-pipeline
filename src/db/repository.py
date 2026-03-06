"""
Shared repository persistence helpers.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


def save(db: Session, obj: T) -> T:
    """Persist an object and flush the session."""
    db.add(obj)
    db.flush()
    return obj


def save_and_refresh(db: Session, obj: T) -> T:
    """Persist an object, flush the session, and refresh it."""
    save(db, obj)
    db.refresh(obj)
    return obj
