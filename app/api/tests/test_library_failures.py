"""Regression coverage for libraries without governance columns and failed crawls."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers.fake_tenant import FakeTenant


def test_missing_governance_columns_fall_back_to_base_metadata(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant,
) -> None:
    library_id = tenant.library_id()
    tenant.add_rule(
        f"lists(guid'{library_id}')/items?",
        400,
        body={"error": {"message": "A governance field does not exist."}},
    )
    response = client.get("/api/v1/documents", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] > 0
    hygiene = client.get("/api/v1/hygiene", headers=auth_headers)
    assert hygiene.status_code == 200
    coverage = next(row for row in hygiene.json()["libraries"] if row["libraryId"] == library_id)
    assert coverage["documentsScanned"] > 0
    assert any("Governance columns" in warning for warning in coverage["warnings"])


def test_only_governance_columns_the_list_has_are_selected(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant,
) -> None:
    library = tenant.library_by_title()
    library["fields"] = ["Title", "FileLeafRef", "ArtifactId", "LifecycleStatus", "DocumentIteration"]
    response = client.get("/api/v1/documents", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] > 0

    items_url = next(
        url for method, url in tenant.calls if method == "GET" and f"lists(guid'{library['id']}')/items?" in url
    )
    select = parse_qs(urlsplit(items_url).query)["$select"][0].split(",")
    assert "LifecycleStatus" in select
    assert "DocumentIteration" in select
    assert "TrustScore" not in select
    hygiene = client.get("/api/v1/hygiene", headers=auth_headers).json()
    coverage = next(row for row in hygiene["libraries"] if row["libraryId"] == library["id"])
    assert any("TrustScore" in warning for warning in coverage["warnings"])
    assert not any("could not be read" in warning for warning in coverage["warnings"])


@pytest.mark.parametrize("route", ["/documents", "/hygiene", "/analytics/duplicates"])
def test_unavailable_library_is_reported_instead_of_returning_empty_success(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant, route: str,
) -> None:
    library_id = tenant.library_id()
    tenant.add_rule(f"lists(guid'{library_id}')/items?", 403, times=2)
    response = client.get(f"/api/v1{route}", headers=auth_headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_forbidden"


@pytest.mark.parametrize("origin,allowed", [("http://localhost:4200", True), ("https://untrusted.example", False)])
def test_unexpected_error_retains_cors_for_trusted_origins_only(
    app: FastAPI, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    origin: str, allowed: bool,
) -> None:
    def fail(**_kwargs: object) -> None:
        raise RuntimeError("Test-only unexpected scan failure")

    monkeypatch.setattr(app.state.container.documents, "list", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/documents", headers={**auth_headers, "Origin": origin})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)
