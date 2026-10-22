"""Live analytics: duplicates, expiry, anomalies and over-exposure, checked against tests/fixtures/expected-analytics.json."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def get(client: TestClient, headers: dict[str, str], path: str) -> dict[str, Any]:
    response = client.get(f"/api/v1{path}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def names(rows: list[dict[str, Any]]) -> list[str]:
    return [row["name"] for row in rows]


def test_duplicate_clusters_and_conflict_candidates_match_the_fixture(
    client: TestClient, auth_headers: dict[str, str], expected: dict[str, Any]
) -> None:
    body = get(client, auth_headers, "/analytics/duplicates")
    wanted = expected["duplicates"]

    assert len(body["exact"]) == wanted["exactClusters"]
    exact = body["exact"][0]
    assert sorted(member["name"] for member in exact["members"]) == wanted["exactMembers"]
    canonical = [member["name"] for member in exact["members"] if member["role"] == "canonical"]
    assert canonical == [wanted["exactCanonical"]]

    assert len(body["near"]) == wanted["nearClusters"]
    near = body["near"][0]
    assert sorted(member["name"] for member in near["members"]) == wanted["nearMembers"]

    pairs = sorted(tuple(sorted((candidate["first"]["name"], candidate["second"]["name"])))
                   for candidate in body["conflictCandidates"])
    assert pairs == [tuple(pair) for pair in wanted["conflictCandidates"]]


def test_expiry_finds_metadata_and_text_dates(client: TestClient, auth_headers: dict[str, str],
                                              expected: dict[str, Any]) -> None:
    body = get(client, auth_headers, "/analytics/expiry")
    assert sorted(names(body["expired"])) == sorted(expected["expiry"]["expired"])
    assert sorted(names(body["reviewOverdue"])) == sorted(expected["expiry"]["reviewOverdue"])
    by_name = {row["name"]: row for row in body["expired"]}
    assert by_name["Old Calibration Report.docx"]["expiry"]["expiredBy"] == ["metadata"]
    assert by_name["Quality Escalation Deck.pptx"]["expiry"]["expiredBy"] == ["text"]
    assert by_name["Quality Escalation Deck.pptx"]["expiry"]["textDates"][0]["date"] == "2026-03-31"


def test_anomaly_scoring_ranks_the_planted_outlier_first(
    client: TestClient, auth_headers: dict[str, str], expected: dict[str, Any]
) -> None:
    body = get(client, auth_headers, "/analytics/anomalies")
    top = body["items"][0]
    assert top["item"]["name"] == expected["anomalies"]["topItem"]
    assert top["isAnomaly"] is expected["anomalies"]["topIsAnomaly"]
    scores = [row["score"] for row in body["items"]]
    assert scores == sorted(scores, reverse=True)


def test_exposure_totals_match_the_fixture_and_each_finding_is_listed_once(
    client: TestClient, auth_headers: dict[str, str], expected: dict[str, Any]
) -> None:
    body = get(client, auth_headers, "/analytics/exposure")
    wanted = expected["exposure"]
    assert body["total"] == wanted["total"]
    assert body["bySeverity"] == wanted["bySeverity"]
    counts: dict[str, int] = {}
    for finding in body["findings"]:
        counts[finding["type"]] = counts.get(finding["type"], 0) + 1
    assert counts == wanted["byType"]
    ids = [finding["id"] for finding in body["findings"]]
    assert len(ids) == len(set(ids))


def test_exposure_type_filter_returns_only_that_type(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = get(client, auth_headers, "/analytics/exposure?type=orphanedAccount")
    assert body["total"] == 3
    assert {finding["type"] for finding in body["findings"]} == {"orphanedAccount"}


def test_orphaned_accounts_are_reported_with_their_state(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = get(client, auth_headers, "/analytics/exposure?type=orphanedAccount")
    states = sorted((finding["member"]["displayName"], finding["member"]["status"]) for finding in body["findings"])
    assert states == [("Dave Former", "disabled"), ("Eve Leaver", "disabled"), ("Gone User", "missing")]


def test_every_analytics_answer_reports_coverage_for_every_library(
    client: TestClient, auth_headers: dict[str, str], expected: dict[str, Any]
) -> None:
    for path in ("/analytics/duplicates", "/analytics/expiry", "/analytics/anomalies", "/analytics/exposure"):
        coverage = {entry["libraryTitle"]: entry for entry in get(client, auth_headers, path)["libraries"]}
        assert set(coverage) == set(expected["libraries"]), path
        for title, figures in expected["libraries"].items():
            assert coverage[title]["documentsScanned"] == figures["documentsScanned"], (path, title)
