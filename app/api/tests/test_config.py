"""Configuration: repo defaults, placeholders, environment overrides (API_CONFIG__ and API_AGENT__), list coercion,
path resolution and cross-file checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.config import ConfigError, load_settings, resolve_path
from tests.helpers.settings import (
    AUDIENCE,
    CLIENT_ID,
    DEPLOYMENT_FIXTURE,
    REPO_CONFIG,
    TENANT_ID,
    write_config,
)

REPO_API_CONFIG = REPO_CONFIG.parent / "app" / "api" / "config" / "api.config.json"


def test_repo_defaults_fail_fast_on_placeholders() -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(REPO_API_CONFIG, env={})
    message = str(caught.value)
    assert "API_CONFIG__auth__audience" in message
    assert "API_CONFIG__auth__clientId" in message
    assert "<API_APP_CLIENT_ID>" in message


def test_repo_defaults_load_once_the_two_identifiers_are_supplied() -> None:
    settings = load_settings(REPO_API_CONFIG, env={
        "API_CONFIG__auth__audience": AUDIENCE,
        "API_CONFIG__auth__clientId": CLIENT_ID,
    })
    assert settings.api.sharePoint.libraryDisplayNames == []
    assert settings.api.sharePoint.defaultLinkRole == "Read"
    assert settings.api.sharedConfig.deploymentPath == "../../config/trusted-knowledge.json"
    assert settings.foundry.configured is False
    assert settings.agent.draftNotification.templateId == "expired-documents"


def test_empty_identifier_override_is_reported_as_not_set(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    with pytest.raises(ConfigError, match="API_CONFIG__auth__clientId"):
        load_settings(config, env={"API_CONFIG__auth__clientId": "   "})


def test_environment_override_changes_a_value_and_is_recorded(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={"API_CONFIG__graph__pageSize": "100"})
    assert settings.api.graph.pageSize == 100
    assert "API_CONFIG__graph__pageSize" in settings.applied_overrides


def test_override_keys_match_case_insensitively(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={"API_CONFIG__GRAPH__PAGESIZE": "120"})
    assert settings.api.graph.pageSize == 120


def test_unknown_override_key_is_rejected(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    with pytest.raises(ConfigError, match="does not match a configuration key"):
        load_settings(config, env={"API_CONFIG__graph__pageSizes": "10"})


def test_non_numeric_override_is_rejected(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    with pytest.raises(ConfigError, match="must be an integer"):
        load_settings(config, env={"API_CONFIG__graph__pageSize": "lots"})


def test_list_overrides_accept_comma_separated_text(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={
        "API_CONFIG__cors__allowedOrigins": "https://ui-one.contoso.com, https://ui-two.contoso.com",
        "API_CONFIG__sharePoint__libraryDisplayNames": "Trusted Knowledge, Field Notes",
    })
    assert settings.api.cors.allowedOrigins == ["https://ui-one.contoso.com", "https://ui-two.contoso.com"]
    assert settings.api.sharePoint.libraryDisplayNames == ["Trusted Knowledge", "Field Notes"]


def test_list_overrides_accept_a_json_array_for_names_with_commas(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={"API_CONFIG__sharePoint__libraryDisplayNames": '["Docs, Archive", "Notes"]'})
    assert settings.api.sharePoint.libraryDisplayNames == ["Docs, Archive", "Notes"]


def test_empty_library_list_override_means_every_library(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={"API_CONFIG__sharePoint__libraryDisplayNames": ""})
    assert settings.api.sharePoint.libraryDisplayNames == []


def test_backslash_and_forward_slash_paths_resolve_to_the_same_file(tmp_path: Path) -> None:
    base = tmp_path / "package"
    assert resolve_path(base, "shared-config\\trusted-knowledge.json") == resolve_path(
        base, "shared-config/trusted-knowledge.json")
    assert resolve_path(base, "shared-config/a.json") == (base / "shared-config" / "a.json").resolve()


def test_descriptor_overrides_resolve_inside_the_package(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    package = config.parent.parent
    shared = package / "shared-config"
    shared.mkdir(parents=True)
    shutil.copy(DEPLOYMENT_FIXTURE, shared / "trusted-knowledge.json")
    shutil.copy(REPO_CONFIG / "governance-vocabulary.json", shared / "governance-vocabulary.json")
    shutil.copy(REPO_CONFIG / "governance-policy.json", shared / "governance-policy.json")
    env = {
        "API_CONFIG__sharedConfig__deploymentPath": "shared-config/trusted-knowledge.json",
        "API_CONFIG__sharedConfig__vocabularyPath": "shared-config/governance-vocabulary.json",
        "API_CONFIG__sharedConfig__policyPath": "shared-config/governance-policy.json",
        "API_CONFIG__cors__allowedOrigins": "https://caldova-aiscr-ui.azurewebsites.net",
        "API_AGENT__foundry__accountName": "foundry-test",
        "API_AGENT__foundry__projectName": "governance-project-test",
        "API_AGENT__foundry__agentName": "governance-agent-test",
    }
    settings = load_settings(config, env=env)
    assert settings.service_root == package.resolve()
    assert settings.site.tenant_id == TENANT_ID
    assert settings.api.cors.allowedOrigins == ["https://caldova-aiscr-ui.azurewebsites.net"]
    assert settings.foundry.configured
    assert settings.foundry.endpoint == "https://foundry-test.services.ai.azure.com/api/projects/governance-project-test"
    assert set(settings.applied_overrides) == set(env)


def test_agent_override_selects_the_foundry_agent_and_nothing_else_is_used(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    settings = load_settings(config, env={"API_AGENT__foundry__agentName": "governance-agent-test"})
    assert settings.foundry.agent_name == "governance-agent-test"
    assert settings.foundry.endpoint is None
    assert settings.foundry.configured is False


def test_placeholder_text_in_the_agent_file_is_rejected(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    agent_path = config.parent / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))
    agent["answers"]["helpIntro"] = "Ask <QUESTION> here"
    agent_path.write_text(json.dumps(agent), encoding="utf-8")
    with pytest.raises(ConfigError, match="placeholder <QUESTION>"):
        load_settings(config, env={})


def test_message_placeholders_must_be_supplied_by_the_code(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    with pytest.raises(ConfigError, match="uses placeholders .*unknownField"):
        load_settings(config, env={"API_AGENT__answers__helpExample": "- {unknownField}"})


def test_prompt_intents_must_exist_in_the_agent_file(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    prompts_path = config.parent / "agent-prompts.json"
    catalog = json.loads(prompts_path.read_text(encoding="utf-8"))
    catalog["prompts"][0]["intent"] = "no-such-intent"
    prompts_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ConfigError, match="no-such-intent"):
        load_settings(config, env={})


def test_prompt_ids_must_be_unique(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    prompts_path = config.parent / "agent-prompts.json"
    catalog = json.loads(prompts_path.read_text(encoding="utf-8"))
    catalog["prompts"][1]["id"] = catalog["prompts"][0]["id"]
    prompts_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ConfigError, match="prompt ids must be unique"):
        load_settings(config, env={})


def test_send_as_reviewer_needs_a_sender(tmp_path: Path) -> None:
    config = write_config(tmp_path, notifications={"mode": "sendAsReviewer"})
    with pytest.raises(ConfigError, match="sender.userPrincipalName must be set"):
        load_settings(config, env={})


def test_repo_agent_file_is_consistent_with_the_prompts_and_findings() -> None:
    settings = load_settings(REPO_API_CONFIG, env={
        "API_CONFIG__auth__audience": AUDIENCE,
        "API_CONFIG__auth__clientId": CLIENT_ID,
    })
    intents = {intent.id for intent in settings.agent.intents}
    assert {prompt.intent for prompt in settings.prompts.prompts} <= intents
    finding_ids = {finding["id"] for finding in settings.governance.findings}
    assert settings.agent.findingIds.missingOwners in finding_ids
    assert settings.agent.draftNotification.findingId in finding_ids
