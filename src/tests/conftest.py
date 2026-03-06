import importlib

import pytest

from src.apps.reports import repository as reports_repo
from src.db.session import SessionLocal
from src.jobs import repository as jobs_repo


@pytest.fixture(scope="session")
def api_base() -> str:
    """Base API prefix."""
    return "/api/v1"


@pytest.fixture()
def db_session():
    """DB session per test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_registry():
    """Keep executor registry clean between tests."""
    import src.jobs.registry as registry

    registry._EXECUTORS.clear()  # type: ignore[attr-defined]
    yield
    registry._EXECUTORS.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def register_report_executors():
    """(Re)register report executors after registry reset."""
    import src.apps.reports.executors as m

    importlib.reload(m)
    return m


@pytest.fixture()
def get_report(db_session):
    """Fetch report from DB (after commits/worker execution)."""

    def _get(report_id: str):
        db_session.expire_all()
        return reports_repo.get(db_session, id=report_id)

    return _get


@pytest.fixture()
def get_job(db_session):
    """Fetch job from DB (after commits/worker execution)."""

    def _get(job_id: str):
        db_session.expire_all()
        return jobs_repo.get(db_session, id=job_id)

    return _get
