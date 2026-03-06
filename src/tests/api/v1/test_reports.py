"""
API tests for report endpoints.

Covers report creation and error mapping for missing reports.
"""

from http import HTTPStatus

from fastapi.testclient import TestClient

from src.main import app
from src.tests.utils import generate_idempotency_key


def test_post_reports_creates_report(api_base):
    """POST /reports should create a report and return its metadata."""
    client = TestClient(app)

    res = client.post(
        f"{api_base}/reports",
        json={},
        headers={"Idempotency-Key": generate_idempotency_key("api-report")},
    )

    assert res.status_code == HTTPStatus.CREATED

    body = res.json()
    assert "id" in body
    assert "status" in body


def test_get_report_not_found_maps_to_404(api_base):
    """GET /reports/{id} should return 404 for missing reports."""
    client = TestClient(app)

    res = client.get(f"{api_base}/reports/missing-id")

    assert res.status_code == HTTPStatus.NOT_FOUND

    body = res.json()
    assert body["detail"] == "Report not found"
    assert body["report_id"] == "missing-id"
