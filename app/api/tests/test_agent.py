"""Agent: evidence answers are deterministic, Foundry is optional and never produces a 500, and the sample prompts
route to their intents."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.foundry import FoundryClient
from app.agent.router import IntentRouter
from app.core.config import Settings, load_settings
from tests.helpers.fake_tenant import FakeTenant

ASK = "/api/v1/agent/messages"
FOUNDRY_ENV = {
    "API_AGENT__foundry__accountName": "foundry-test",
    "API_AGENT__foundry__projectName": "governance-project-test",
    "API_AGENT__foundry__agentName": "governance-agent-test",
}


def ask(client: TestClient, headers: dict[str, str], prompt: str, **extra: Any) -> dict[str, Any]:
    response = client.post(ASK, json={"prompt": prompt, **extra}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("prompt", "intent"),
    [
        ("What can you do?", "help"),
        ("What can alice@contoso.com access?", "access-review"),
        ("Can you summarize the cleanup backlog?", "backlog-summary"),
        ("Summarize meeting 12 transcript and cite the recording", "meeting-transcripts"),
    ],
)
def test_help_and_access_questions_are_not_confused(prompt: str, intent: str, settings: Settings) -> None:
    router = IntentRouter(settings.agent.intents, settings.agent.fallbackIntent)
    assert router.route(prompt).id == intent


def test_prompts_endpoint_publishes_the_prompt_file(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/agent/prompts", headers=auth_headers).json()
    assert set(body) == {"schemaVersion", "provisional", "note", "placeholders", "prompts"}
    assert body["schemaVersion"] == "sp-acl-agent-prompts/v1"
    assert body["provisional"] is False
    assert "{userUpn}" in body["placeholders"]
    assert len(body["prompts"]) == 14
    assert {prompt["issueId"] for prompt in body["prompts"]} == {
        "scattered-content", "permissions-vs-audience", "decisions-in-inboxes", "meeting-transcripts"}
    assert all(prompt["issueLabel"] for prompt in body["prompts"])


def test_every_sample_prompt_routes_to_its_intent(client: TestClient, auth_headers: dict[str, str],
                                                  settings: Settings) -> None:
    for prompt in settings.prompts.prompts:
        text = prompt.text.replace("{userUpn}", "alice@contoso.com")
        body = ask(client, auth_headers, text)
        assert body["intent"] == prompt.intent, prompt.id
        assert body["foundry"]["status"] == "notConfigured", prompt.id


def test_without_foundry_the_answer_is_exactly_the_evidence_lines(client: TestClient,
                                                                  auth_headers: dict[str, str]) -> None:
    body = ask(client, auth_headers, "Which documents are expired or past their review date?")
    assert body["mode"] == "evidence"
    assert body["answer"] == "\n".join(body["evidence"]["lines"])
    assert body["foundry"] == {"configured": False, "status": "notConfigured",
                               "message": body["foundry"]["message"]}
    assert body["warnings"] == []


def test_evidence_answers_are_deterministic(client: TestClient, auth_headers: dict[str, str]) -> None:
    first = ask(client, auth_headers, "Which documents have no knowledge owner?")
    second = ask(client, auth_headers, "Which documents have no knowledge owner?")
    assert first["answer"] == second["answer"]
    assert first["evidence"]["facts"] == second["evidence"]["facts"]


def test_the_question_names_a_user_by_upn(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = ask(client, auth_headers, "What can bob@contoso.com access in this site, and how was each permission granted?")
    assert body["intent"] == "access-review"
    assert body["evidence"]["facts"]["userPrincipalName"] == "bob@contoso.com"


def test_answer_sentences_come_from_the_agent_file(build_app, config_path, auth_headers: dict[str, str]) -> None:
    settings = load_settings(config_path, env={"API_AGENT__answers__helpIntro": "Ask about governance here:"})
    client = TestClient(build_app(settings))
    body = ask(client, auth_headers, "help")
    assert body["intent"] == "help"
    assert body["answer"].splitlines()[0] == "Ask about governance here:"


def test_example_limit_comes_from_the_agent_file(build_app, config_path, auth_headers: dict[str, str]) -> None:
    settings = load_settings(config_path, env={"API_AGENT__limits__maxExamples": "1"})
    client = TestClient(build_app(settings))
    body = ask(client, auth_headers, "Who can access the library through which group or sharing link?")
    examples = [line for line in body["evidence"]["lines"] if line.startswith("  ")]
    assert len(examples) <= 1


def test_evidence_mode_never_calls_foundry(build_app, config_path, auth_headers: dict[str, str],
                                           tenant: FakeTenant) -> None:
    settings = load_settings(config_path, env=FOUNDRY_ENV)
    client = TestClient(build_app(settings))
    body = ask(client, auth_headers, "Which documents have no knowledge owner?", mode="evidence")
    assert body["mode"] == "evidence"
    assert body["foundry"]["status"] == "notRequested"
    assert tenant.foundry_calls == []


def test_foundry_answers_when_it_is_configured_through_the_environment(
    build_app, config_path, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    settings = load_settings(config_path, env=FOUNDRY_ENV)
    client = TestClient(build_app(settings))
    body = ask(client, auth_headers, "Which documents have no knowledge owner?")
    assert body["mode"] == "foundry"
    assert body["foundry"]["status"] == "used"
    assert body["answer"] == "Grounded answer from the Foundry agent."
    assert len(tenant.foundry_calls) == 1
    assert tenant.foundry_calls[0]["agent_reference"]["name"] == "governance-agent-test"


def test_a_foundry_outage_keeps_the_evidence_answer(build_app, config_path, auth_headers: dict[str, str],
                                                    tenant: FakeTenant) -> None:
    tenant.foundry_status = 500
    client = TestClient(build_app(load_settings(config_path, env=FOUNDRY_ENV)))
    body = ask(client, auth_headers, "Which documents have no knowledge owner?")
    assert body["mode"] == "evidence"
    assert body["foundry"]["status"] == "unavailable"
    assert body["warnings"] and "Microsoft Foundry" in body["warnings"][0]
    assert body["answer"] == "\n".join(body["evidence"]["lines"])


def test_an_unexpected_foundry_failure_is_contained(build_app, config_path, auth_headers: dict[str, str],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self: FoundryClient, text_input: str) -> str:
        raise RuntimeError("simulated client fault")

    monkeypatch.setattr(FoundryClient, "respond", explode)
    client = TestClient(build_app(load_settings(config_path, env=FOUNDRY_ENV)))
    body = ask(client, auth_headers, "Which documents have no knowledge owner?")
    assert body["foundry"]["status"] == "unavailable"
    assert body["mode"] == "evidence"
    assert body["answer"] == "\n".join(body["evidence"]["lines"])


def test_owner_notification_prompt_drafts_and_sends_nothing(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = ask(client, auth_headers, "Draft approval requests to the owners of expired or unowned documents")
    assert body["intent"] == "owner-notification"
    statuses = {item["status"] for item in body["evidence"]["items"]}
    assert statuses <= {"draft"}
    assert tenant.sent_mail == []


def test_help_lists_the_sample_prompts(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = ask(client, auth_headers, "What can you do? Examples please")
    assert body["intent"] == "help"
    assert body["evidence"]["facts"]["examples"] == 14
