"""
Unit of Work pattern for explicit transaction boundaries.
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session


class UnitOfWork:
    """
    An active transaction context.

    Wraps a SQLAlchemy Session and provides explicit commit/rollback.

    Usage:

        with UnitOfWork(db) as uow:
            result = some_service(uow, ...)

    commit() runs on clean exit
    rollback() runs on exception
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        """The underlying SQLAlchemy session."""
        return self._session

    def commit(self) -> None:
        """Commit the current transaction."""
        self._session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self._session.rollback()

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
