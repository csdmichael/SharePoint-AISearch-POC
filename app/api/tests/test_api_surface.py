"""Public surface: health (root and under the API prefix), policy, OpenAPI and the interactive documentation."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_is_public_at_the_root_and_under_the_api_prefix(client: TestClient) -> None:
    root = client.get("/health")
    prefixed = client.get("/api/v1/health")
    assert root.status_code == 200
    assert prefixed.status_code == 200
    assert root.json()["status"] == "ok"
    assert root.json() == prefixed.json()


def test_policy_is_public_and_publishes_the_governance_labels(client: TestClient) -> None:
    response = client.get("/api/v1/policy")
    assert response.status_code == 200
    body = response.json()
    assert "lifecycleStatus" in body["labels"]
    assert body["hygiene"]["findings"]


def test_openapi_document_uses_the_configured_title_and_lists_the_routes(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "SharePoint Governance API"
    assert "/health" in document["paths"]
    assert "/api/v1/agent/messages" in document["paths"]
    assert "/api/v1/notifications/{notificationId}/send" in document["paths"]


def test_interactive_documentation_responds(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "swagger" in response.text.lower()
