"""
Database engine and session configuration.

Provides:
- SQLAlchemy engine
- Session factory
- FastAPI dependency for DB session management
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
    FastAPI dependency that provides a scoped database session.

    Ensures the session is properly closed after request lifecycle.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
