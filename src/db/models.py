"""
Model registry.

Importing this module ensures all ORM models are registered on Base.metadata.
Used by Alembic autogenerate (and any tooling that needs full metadata).
"""

# Import modules that declare SQLAlchemy models.
import src.apps.reports.models  # noqa: F401
import src.jobs.models  # noqa: F401
