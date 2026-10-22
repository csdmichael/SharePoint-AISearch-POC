"""Inbound authentication: Entra ID bearer tokens validated against the tenant JWKS."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
import jwt
from fastapi import Request
from jwt.algorithms import RSAAlgorithm

from app.core.config import AuthConfig
from app.core.errors import ForbiddenError, UnauthorizedError, UpstreamError

ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256",)
REQUIRED_CLAIMS: list[str] = ["exp", "iat", "aud", "iss"]
BEARER_SCHEME = "bearer"
CHALLENGE_REALM = "sp-acl-api"


@dataclass(frozen=True)
class Principal:
    subject: str | None
    upn: str | None
    name: str | None
    roles: tuple[str, ...]
    tenant_id: str | None
    app_id: str | None


class JwksCache:
    """Caches the tenant's RSA signing keys and refreshes them on expiry or on an unknown key id."""

    def __init__(
        self,
        url: str,
        *,
        client: httpx.Client,
        cache_seconds: int,
        min_refresh_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._client = client
        self._cache_seconds = cache_seconds
        self._min_refresh_seconds = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def signing_key(self, kid: str) -> Any:
        with self._lock:
            now = self._clock()
            if self._fetched_at is None or now - self._fetched_at >= self._cache_seconds:
                self._refresh(now)
            elif kid not in self._keys and now - self._fetched_at >= self._min_refresh_seconds:
                self._refresh(now)
            key = self._keys.get(kid)
            if key is None:
                raise UnauthorizedError("The token was signed with an unknown key.", code="invalid_token")
            return key

    def _refresh(self, now: float) -> None:
        try:
            response = self._client.get(self._url)
        except httpx.HTTPError as exc:
            raise UpstreamError(
                "Entra ID", "signing keys could not be downloaded", code="identity_unavailable", status_code=503
            ) from exc
        if response.status_code != 200:
            raise UpstreamError(
                "Entra ID",
                f"signing keys returned HTTP {response.status_code}",
                code="identity_unavailable",
                status_code=503,
            )
        keys: dict[str, Any] = {}
        for jwk in response.json().get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("kid"):
                keys[str(jwk["kid"])] = RSAAlgorithm.from_jwk(json.dumps(jwk))
        self._keys = keys
        self._fetched_at = now


class TokenValidator:
    """Checks the signature, issuer, lifetime and audience of a token, then the configured app role.

    An API that requests v2 access tokens receives aud = its client id (a GUID). An API that does not receive
    aud = api://<client id>. Both forms are accepted; any other audience is refused with invalid_audience.
    """

    def __init__(
        self,
        auth: AuthConfig,
        tenant_id: str,
        *,
        jwks: JwksCache,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._audiences = list(dict.fromkeys(value for value in (auth.audience, auth.clientId) if value))
        self._issuer = auth.validIssuerTemplate.replace("{tenantId}", tenant_id)
        self._required_role = auth.requiredRole
        self._leeway = auth.clockSkewSeconds
        self._jwks = jwks
        self._clock = clock

    @property
    def required_role(self) -> str:
        return self._required_role

    @property
    def audiences(self) -> tuple[str, ...]:
        return tuple(self._audiences)

    def validate(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise UnauthorizedError("The bearer token is malformed.", code="invalid_token") from None
        if header.get("alg") not in ALLOWED_ALGORITHMS or not header.get("kid"):
            raise UnauthorizedError("The bearer token uses an unsupported signature.", code="invalid_token")
        key = self._jwks.signing_key(str(header["kid"]))
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._audiences,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise UnauthorizedError("The bearer token has expired.", code="token_expired") from None
        except jwt.InvalidAudienceError:
            raise UnauthorizedError("The bearer token audience is not this API.", code="invalid_audience") from None
        except jwt.InvalidIssuerError:
            raise UnauthorizedError("The bearer token issuer is not the configured tenant.", code="invalid_issuer") from None
        except jwt.PyJWTError:
            raise UnauthorizedError("The bearer token could not be validated.", code="invalid_token") from None

        roles_claim = claims.get("roles") or []
        roles = tuple(str(role) for role in roles_claim) if isinstance(roles_claim, list) else ()
        if self._required_role not in roles:
            raise ForbiddenError(f"The '{self._required_role}' app role is required for this endpoint.")
        upn = claims.get("upn") or claims.get("preferred_username")
        return Principal(
            subject=claims.get("oid") or claims.get("sub"),
            upn=str(upn).lower() if upn else None,
            name=claims.get("name"),
            roles=roles,
            tenant_id=claims.get("tid"),
            app_id=claims.get("appid") or claims.get("azp"),
        )


def bearer_token(header_value: str | None) -> str:
    challenge = {"WWW-Authenticate": f'Bearer realm="{CHALLENGE_REALM}"'}
    if not header_value:
        raise UnauthorizedError("A bearer token is required.", code="unauthorized", headers=challenge)
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != BEARER_SCHEME or not token.strip():
        raise UnauthorizedError(
            "The Authorization header must carry a bearer token.", code="unauthorized", headers=challenge
        )
    return token.strip()


def require_auditor(request: Request) -> Principal:
    """FastAPI dependency: a valid Entra token that carries the configured auditor role."""

    token = bearer_token(request.headers.get("authorization"))
    principal = request.app.state.container.validator.validate(token)
    request.state.principal = principal
    return principal
