"""
SQLAlchemy declarative base class.

All ORM models should inherit from this base.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass
