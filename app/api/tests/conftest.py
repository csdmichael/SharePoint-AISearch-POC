"""Shared fixtures: the fixture tenant, signing keys, settings built from the real config files, and clients."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pytest
from azure.core.credentials import AccessToken
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, load_settings
from app.factory import create_app
from tests.helpers.fake_tenant import FakeTenant, load_tenant
from tests.helpers.settings import TokenFactory, read_expected, write_config


class FakeCredential:
    """Stands in for the managed identity. The token encodes the requested scope so tests can assert it."""

    def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken(f"token-for:{scopes[0]}", int(time.time()) + 3600)


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def tenant(tokens: TokenFactory) -> FakeTenant:
    fake = FakeTenant(load_tenant())
    fake.jwks = tokens.jwks
    return fake


@pytest.fixture
def credential() -> FakeCredential:
    return FakeCredential()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return write_config(tmp_path)


@pytest.fixture
def settings(config_path: Path) -> Settings:
    return load_settings(config_path, env={})


@pytest.fixture
def build_app(tenant: FakeTenant, credential: FakeCredential) -> Callable[..., FastAPI]:
    def _build(settings_obj: Settings, **kwargs: Any) -> FastAPI:
        return create_app(
            settings_obj,
            transport=tenant.transport(),
            credential=credential,
            sleep=lambda _seconds: None,
            **kwargs,
        )

    return _build


@pytest.fixture
def app(build_app: Callable[..., FastAPI], settings: Settings) -> FastAPI:
    return build_app(settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers(tokens: TokenFactory, settings: Settings) -> dict[str, str]:
    """A valid bearer header: a v2-style token signed by the fixture tenant key, carrying the required app role."""

    token = tokens.make(roles=[settings.api.auth.requiredRole])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def expected() -> dict[str, Any]:
    return read_expected()
