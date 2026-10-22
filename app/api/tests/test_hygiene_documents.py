"""Hygiene metrics and findings, governance document list and detail. Counts come from tests/fixtures/expected-analytics.json."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers.fake_tenant import FakeTenant


def get(client: TestClient, headers: dict[str, str], path: str) -> Any:
    response = client.get(f"/api/v1{path}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_hygiene_finding_counts_match_the_fixture(client: TestClient, auth_headers: dict[str, str],
                                                  expected: dict[str, Any]) -> None:
    body = get(client, auth_headers, "/hygiene")
    counts = {finding["id"]: finding["count"] for finding in body["findings"]}
    assert counts == expected["hygiene"]["findings"]


def test_hygiene_metric_values_match_the_fixture(client: TestClient, auth_headers: dict[str, str],
                                                 expected: dict[str, Any]) -> None:
    body = get(client, auth_headers, "/hygiene")
    values = {metric["key"]: metric["value"] for metric in body["metrics"]}
    assert values == expected["hygiene"]["metrics"]


def test_hygiene_finding_detail_lists_the_documents_behind_it(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = get(client, auth_headers, "/hygiene/findings/draft-documents")
    assert body["count"] == 6
    assert "Thermal Notes.xlsx" in [document["name"] for document in body["documents"]]
    assert all(document["reason"] == "LifecycleStatus = Draft" for document in body["documents"])


def test_unknown_hygiene_finding_is_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/hygiene/findings/no-such-finding", headers=auth_headers)
    assert response.status_code == 404


def test_document_list_filters_by_lifecycle_status(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = get(client, auth_headers, "/documents?lifecycleStatus=Draft&pageSize=50")
    assert body["total"] == 6
    assert "Onboarding Notes.xlsx" in [item["name"] for item in body["items"]]


def test_document_list_rejects_an_unknown_sort_field(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/documents?sort=nonsense", headers=auth_headers)
    assert response.status_code == 400


def test_document_detail_shows_duplicate_roles_expiry_and_owner(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    item_id = tenant.item_id("Failure Analysis Procedure (copy).docx")
    body = get(client, auth_headers, f"/documents/{item_id}")
    assert body["knowledgeOwner"] == "alice@contoso.com"
    kinds = sorted(role["kind"] for role in body["liveDuplicateRoles"])
    assert kinds == ["exact", "near"]
    assert body["liveExpiry"]["expired"] is False


def test_document_detail_for_a_folder_is_not_found(client: TestClient, auth_headers: dict[str, str],
                                                   tenant: FakeTenant) -> None:
    response = client.get(f"/api/v1/documents/{tenant.item_id('Engineering')}", headers=auth_headers)
    assert response.status_code == 404
