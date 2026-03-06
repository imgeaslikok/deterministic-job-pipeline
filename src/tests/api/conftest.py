import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture(scope="session")
def api_version() -> str:
    return "v1"


@pytest.fixture(scope="session")
def api_base(api_version: str) -> str:
    return f"/api/{api_version}"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)