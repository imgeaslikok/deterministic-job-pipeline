"""
Shared pytest fixtures for API tests.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="session")
def api_version() -> str:
    """Return the API version used in tests."""
    return "v1"


@pytest.fixture(scope="session")
def api_base(api_version: str) -> str:
    """Return the base path for the API version."""
    return f"/api/{api_version}"


@pytest.fixture()
def client() -> TestClient:
    """Provide a FastAPI test client."""
    return TestClient(app)
