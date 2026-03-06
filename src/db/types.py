"""
Custom SQLAlchemy type helpers.
"""

from __future__ import annotations

from enum import Enum as PyEnum

from sqlalchemy import Enum


def enum_value_type(enum_cls: type[PyEnum], *, name: str) -> Enum:
    """Create an Enum column type storing enum values instead of names."""
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )
