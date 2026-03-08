"""
Database engine and session setup.

Provides the SQLAlchemy engine, session factory, and FastAPI
dependency for database sessions.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import settings

from .unit_of_work import UnitOfWork

# Engine with connection health checks and configurable pool settings
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
)

# Session factory (explicit transaction control)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    """
    Provide a database session for FastAPI requests.
    """
    with SessionLocal() as db:
        yield db


def get_uow():
    """Provide a UnitOfWork for write operations."""
    with SessionLocal() as db:
        yield UnitOfWork(db)
