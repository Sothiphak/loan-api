"""Run with: python train.py && pytest -v"""
import os

import pytest
from fastapi.testclient import TestClient

from main import APPLICATIONS, app

GOOD = {"amount_usd": 1500, "term_months": 12, "monthly_income_usd": 350.0, "previous_loans": 1, "late_payments": 0}
AUTH = {"X-API-Key": os.environ["API_KEY"]}


@pytest.fixture
def client():
    APPLICATIONS.clear()
    with TestClient(app) as c:  # "with" runs the lifespan, so the model is loaded
        yield c


def test_health_reports_model_version_and_commit(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model_version"] == "1.0.0"
    assert "git_sha" in body


def test_prediction_is_a_probability(client):
    body = client.post("/api/v1/predictions", json=GOOD, headers=AUTH).json()
    assert 0 <= body["default_probability"] <= 1
    assert body["risk_band"] in {"low", "medium", "high"}


def test_amount_above_limit_is_rejected(client):
    assert client.post("/api/v1/predictions", json={**GOOD, "amount_usd": 9000}, headers=AUTH).status_code == 422


def test_create_and_read_application(client):
    created = client.post("/api/v1/applications", json={**GOOD, "borrower_id": 1042}, headers=AUTH)
    assert created.status_code == 201
    app_id = created.json()["id"]
    assert client.get(f"/api/v1/applications/{app_id}", headers=AUTH).json()["borrower_id"] == 1042


def test_missing_application_is_404(client):
    assert client.get("/api/v1/applications/99999", headers=AUTH).status_code == 404


# --- API key checks (Lesson 6.6) ---
def test_missing_api_key_is_401(client):
    assert client.post("/api/v1/predictions", json=GOOD).status_code == 401


def test_wrong_api_key_is_403(client):
    assert client.post("/api/v1/predictions", json=GOOD, headers={"X-API-Key": "wrong"}).status_code == 403


def test_health_and_docs_need_no_key(client):
    assert client.get("/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_borrower_applications_lists_only_that_borrower(client):
    client.post("/api/v1/applications", json={**GOOD, "borrower_id": 1042}, headers=AUTH)
    client.post("/api/v1/applications", json={**GOOD, "borrower_id": 7}, headers=AUTH)
    body = client.get("/api/v1/borrowers/1042/applications", headers=AUTH).json()
    assert [a["borrower_id"] for a in body] == [1042]


def test_openapi_documents_auth_errors(client):
    paths = client.get("/openapi.json").json()["paths"]
    responses = paths["/api/v1/predictions"]["post"]["responses"]
    assert {"401", "403"} <= set(responses)



def test_score_is_not_inverted(client):
    """Regression: a release once returned 1 - p, and the bounds test could not see it."""
    body = client.post("/api/v1/predictions", json=GOOD, headers=AUTH).json()
    assert abs(body["default_probability"] - 0.095) < 0.01
    assert body["risk_band"] == "low"
