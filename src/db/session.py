"""
Database engine and session setup.

Provides the SQLAlchemy engine, session factory, and FastAPI
dependency for database sessions.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import settings

# Engine with connection health checks enabled
engine = create_engine(settings.database_url, pool_pre_ping=True)

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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
