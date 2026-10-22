"""Owner notifications: drafts land in the outbox, approval comes first, and nothing is sent in dryRun."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import load_settings
from tests.helpers.fake_tenant import FakeTenant
from tests.helpers.settings import write_config

DRAFT_BODY = {"templateId": "expired-documents", "findingId": "expired-documents"}


def create_drafts(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.post("/api/v1/notifications/drafts", json=DRAFT_BODY, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["created"]


def test_drafts_are_written_to_the_outbox_and_nothing_is_sent(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant, settings
) -> None:
    created = create_drafts(client, auth_headers)
    assert len(created) == 2
    assert {draft["status"] for draft in created} == {"draft"}
    assert {draft["ownerUpn"] for draft in created} == {"alice@contoso.com"}

    outbox = json.loads(settings.outbox_path.read_text(encoding="utf-8"))
    assert len(outbox["notifications"]) == 2
    assert tenant.sent_mail == []


def test_a_second_request_inside_the_dedupe_window_creates_nothing(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    create_drafts(client, auth_headers)
    response = client.post("/api/v1/notifications/drafts", json=DRAFT_BODY, headers=auth_headers)
    body = response.json()
    assert body["created"] == []
    assert {entry["reason"] for entry in body["skipped"]} == {"withinDedupeWindow"}


def test_a_draft_cannot_be_sent_before_it_is_approved(client: TestClient, auth_headers: dict[str, str]) -> None:
    draft_id = create_drafts(client, auth_headers)[0]["id"]
    response = client.post(f"/api/v1/notifications/{draft_id}/send", headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_approved"


def test_dry_run_send_is_refused_and_nothing_reaches_graph(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    draft_id = create_drafts(client, auth_headers)[0]["id"]
    approved = client.post(f"/api/v1/notifications/{draft_id}/approve", headers=auth_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    sent = client.post(f"/api/v1/notifications/{draft_id}/send", headers=auth_headers)
    assert sent.status_code == 200
    body = sent.json()
    assert body["status"] == "dryRunRecorded"
    assert "nothing was delivered" in body["delivery"]
    assert tenant.sent_mail == []
    assert not any(method == "POST" and "sendMail" in url for method, url in tenant.calls)


def test_listing_filters_by_status_and_reports_the_mode(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_drafts(client, auth_headers)
    body = client.get("/api/v1/notifications?status=draft", headers=auth_headers).json()
    assert body["total"] == 2
    assert body["mode"] == "dryRun"
    bad = client.get("/api/v1/notifications?status=teleported", headers=auth_headers)
    assert bad.status_code == 400


def test_unknown_template_is_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/notifications/drafts",
                           json={"templateId": "no-such-template", "findingId": "expired-documents"},
                           headers=auth_headers)
    assert response.status_code == 404


def test_a_draft_request_needs_exactly_one_target(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/notifications/drafts",
                           json={"templateId": "expired-documents"}, headers=auth_headers)
    assert response.status_code == 422


def test_send_as_reviewer_sends_through_graph_when_the_mode_allows_it(
    build_app, tmp_path: Path, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    config = write_config(tmp_path / "reviewer", notifications={
        "mode": "sendAsReviewer",
        "sender": {"userPrincipalName": "reviewer@contoso.com"},
    })
    client = TestClient(build_app(load_settings(config, env={})))
    draft_id = create_drafts(client, auth_headers)[0]["id"]
    client.post(f"/api/v1/notifications/{draft_id}/approve", headers=auth_headers)
    sent = client.post(f"/api/v1/notifications/{draft_id}/send", headers=auth_headers).json()
    assert sent["status"] == "sent"
    assert len(tenant.sent_mail) == 1
    assert tenant.sent_mail[0]["sender"] == "reviewer@contoso.com"
    message = tenant.sent_mail[0]["body"]["message"]
    assert message["toRecipients"][0]["emailAddress"]["address"] == "alice@contoso.com"
