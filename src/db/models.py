"""
Model registry.

Importing this module ensures all ORM models are registered on Base.metadata.
"""

import src.apps.reports.models  # noqa: F401
import src.jobs.models  # noqa: F401
import src.outbox.models  # noqa: F401
