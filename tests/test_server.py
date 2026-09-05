"""Smoke test of the companion API, including the extension endpoints' auth."""

import pytest
from fastapi.testclient import TestClient

from jobwrapper.server.app import create_app, get_state


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.fixture(scope="module")
def token():
    return get_state().config.server.token


def test_status(client):
    payload = client.get("/api/status").json()
    assert "profile_complete" in payload and "applications" in payload


def test_schema_describes_every_section(client):
    payload = client.get("/api/schema").json()
    ids = [s["id"] for s in payload["schema"]["sections"]]
    for expected in ("identity", "address", "authorization", "education", "experience", "eeo"):
        assert expected in ids


def test_profile_roundtrip(client):
    profile = client.get("/api/profile").json()
    profile["identity"]["legal_first_name"] = "Testy"
    profile["identity"]["date_of_birth"] = ""          # blank dates must be accepted
    response = client.put("/api/profile", json=profile)
    assert response.status_code == 200
    assert client.get("/api/profile").json()["identity"]["legal_first_name"] == "Testy"


def test_profile_rejects_garbage(client):
    assert client.put("/api/profile", json={"identity": {"legal_first_name": 42, "pronouns": []}}).status_code == 422


def test_extension_endpoints_require_the_token(client):
    assert client.get("/api/ext/ping").status_code == 401
    assert client.get("/api/ext/ping", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_extension_analyze_and_plan(client, token):
    headers = {"authorization": f"Bearer {token}"}
    analyzed = client.post("/api/ext/analyze", headers=headers, json={
        "company": "Vector Labs", "title": "Senior Backend Engineer", "location": "Remote",
        "url": "https://vectorlabs.example/jobs/1",
        "description": "Go, Kubernetes, Terraform, PostgreSQL. 5+ years backend.",
    }).json()
    assert "job_id" in analyzed and isinstance(analyzed["score"], int)

    plan = client.post("/api/ext/plan", headers=headers, json={
        "job_id": analyzed["job_id"], "ats": "greenhouse", "use_llm": False,
        "url": "https://vectorlabs.example/apply",
        "fields": [
            {"selector": "#fn", "name": "job_application[first_name]", "label": "First Name",
             "required": True},
            {"selector": "#ssn", "name": "ssn", "label": "Social Security Number",
             "required": True},
        ],
    }).json()
    assert any(f["field_key"] == "first_name" for f in plan["fields"])
    assert plan["blocking"], "an SSN field must block the plan"


def test_artifact_endpoint_refuses_paths_outside_the_data_root(client):
    assert client.get("/api/artifact", params={"path": "/etc/passwd"}).status_code == 403
