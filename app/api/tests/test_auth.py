"""Authentication: 401 without a valid token, 403 without the Auditor role, and the audience rules for v2 tokens."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers.settings import AUDIENCE, CLIENT_ID, TokenFactory

ME = "/api/v1/me"
FOREIGN_AUDIENCE = "api://00000000-0000-4000-8000-000000000999"
OTHER_TENANT_ISSUER = "https://login.microsoftonline.com/99999999-0000-0000-0000-000000000000/v2.0"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_request_without_token_is_401_with_a_challenge(client: TestClient) -> None:
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_malformed_authorization_header_is_401(client: TestClient) -> None:
    response = client.get(ME, headers={"Authorization": "Token not-a-bearer"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_token_signed_by_another_key_is_401(client: TestClient) -> None:
    forged = TokenFactory().make(roles=["Auditor"])
    response = client.get(ME, headers=bearer(forged))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_token_without_the_auditor_role_is_403(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(roles=["Reader"])))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_auditor_token_is_accepted_and_its_roles_are_reported(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(roles=["Auditor"], upn="Auditor@Contoso.com")))
    assert response.status_code == 200
    body = response.json()
    assert body["userPrincipalName"] == "auditor@contoso.com"
    assert body["roles"] == ["Auditor"]


@pytest.mark.parametrize("audience", [AUDIENCE, CLIENT_ID], ids=["api-uri", "client-id-guid"])
def test_both_audience_forms_are_accepted(client: TestClient, tokens: TokenFactory, audience: str) -> None:
    response = client.get(ME, headers=bearer(tokens.make(audience=audience)))
    assert response.status_code == 200


def test_audience_of_another_app_is_rejected(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(audience=FOREIGN_AUDIENCE)))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_audience"


def test_token_from_another_tenant_is_rejected(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(issuer=OTHER_TENANT_ISSUER)))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_issuer"


def test_expired_token_is_rejected(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(expires_in=-3600)))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_symmetric_signature_is_rejected(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(algorithm="HS256")))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_unknown_signing_key_id_is_rejected(client: TestClient, tokens: TokenFactory) -> None:
    response = client.get(ME, headers=bearer(tokens.make(kid="key-not-published-by-tenant")))
    assert response.status_code == 401
