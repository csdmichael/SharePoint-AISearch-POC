"""Test-only helpers: build settings from the real config files plus fixture overrides, and sign test tokens."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = ROOT / "config"
REPO_CONFIG = ROOT.parents[1] / "config"
DEPLOYMENT_FIXTURE = ROOT / "tests" / "fixtures" / "config" / "trusted-knowledge.json"
EXPECTED_ANALYTICS = ROOT / "tests" / "fixtures" / "expected-analytics.json"
AS_OF = "2026-10-21"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "9f3c0a2e-7d11-4c55-8a2b-1234567890ab"
AUDIENCE = f"api://{CLIENT_ID}"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
KEY_ID = "test-signing-key"


def read_source(name: str) -> dict[str, Any]:
    return json.loads((SOURCE_CONFIG / name).read_text(encoding="utf-8"))


def read_expected() -> dict[str, Any]:
    return json.loads(EXPECTED_ANALYTICS.read_text(encoding="utf-8"))


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def write_config(
    root: Path,
    *,
    api: dict[str, Any] | None = None,
    analytics: dict[str, Any] | None = None,
    notifications: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
) -> Path:
    """Copies the real config files into root\\app\\api\\config and applies overrides. Shared paths point at fixtures."""

    config_dir = root / "app" / "api" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    api_config = read_source("api.config.json")
    api_config = deep_merge(api_config, {
        "auth": {"clientId": CLIENT_ID, "audience": AUDIENCE},
        "graph": {"retryBackoffSeconds": 0},
        "sharePoint": {"pageSize": 3},
        "hygiene": {"asOfDate": AS_OF},
        "sharedConfig": {
            "deploymentPath": str(DEPLOYMENT_FIXTURE),
            "vocabularyPath": str(REPO_CONFIG / "governance-vocabulary.json"),
            "policyPath": str(REPO_CONFIG / "governance-policy.json"),
        },
    })
    api_config = deep_merge(api_config, api or {})
    notification_config = read_source("notifications.json")
    notification_config = deep_merge(notification_config, {
        "outboxPath": str(root / "state" / "outbox.json"),
    })
    notification_config = deep_merge(notification_config, notifications or {})
    outputs = {
        "api.config.json": api_config,
        "analytics.json": deep_merge(read_source("analytics.json"), analytics or {}),
        "notifications.json": notification_config,
        "agent.json": deep_merge(read_source("agent.json"), agent or {}),
        "agent-prompts.json": read_source("agent-prompts.json"),
        "knowledge-capture.json": deep_merge(read_source("knowledge-capture.json"), {
            "publish": {"demoStatePath": str(root / "state" / "knowledge-capture"), "siteId": "default"},
        }),
    }
    outputs["knowledge-capture.json"] = deep_merge(outputs["knowledge-capture.json"], knowledge or {})
    for name, content in outputs.items():
        (config_dir / name).write_text(json.dumps(content, indent=2), encoding="utf-8")
    return config_dir / "api.config.json"


class TokenFactory:
    def __init__(self) -> None:
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._pem = self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        jwk = json.loads(RSAAlgorithm.to_jwk(self._private.public_key()))
        jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
        self.jwks: dict[str, Any] = {"keys": [jwk]}

    def make(
        self,
        *,
        audience: str = AUDIENCE,
        issuer: str = ISSUER,
        roles: list[str] | None = None,
        expires_in: int = 3600,
        issued_at: datetime | None = None,
        kid: str | None = KEY_ID,
        algorithm: str = "RS256",
        upn: str = "auditor@contoso.com",
    ) -> str:
        now = issued_at or datetime.now(timezone.utc)
        payload = {
            "aud": audience,
            "iss": issuer,
            "tid": TENANT_ID,
            "oid": "auditor-object-id",
            "upn": upn,
            "name": "Test Auditor",
            "appid": "caller-app-id",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
            "roles": ["Auditor"] if roles is None else roles,
        }
        headers = {"kid": kid} if kid else {}
        if algorithm == "HS256":
            return jwt.encode(payload, "not-the-tenant-key", algorithm="HS256", headers=headers)
        return jwt.encode(payload, self._pem, algorithm="RS256", headers=headers)
