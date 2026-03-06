"""
Model registry.

Importing this module ensures all ORM models are registered on Base.metadata.
Used by Alembic autogenerate (and any tooling that needs full metadata).
"""

import src.apps.reports.models  # noqa: F401
import src.jobs.models  # noqa: F401
import src.outbox.models  # noqa: F401
