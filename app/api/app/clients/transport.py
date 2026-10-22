"""Outbound HTTP: managed-identity tokens, retries with Retry-After, and upstream error mapping."""

from __future__ import annotations

import email.utils
import threading
import time
from typing import Any, Callable, Mapping

import httpx
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from app.core.config import IdentityConfig
from app.core.errors import UpstreamError, UpstreamNotFoundError

RETRYABLE_STATUS: frozenset[int] = frozenset({429, 502, 503, 504})
USER_AGENT = "sp-acl-api/1.0"


def build_credential(identity: IdentityConfig, environ: Mapping[str, str]) -> Any:
    """Managed identity inside App Service (system-assigned unless a client id is configured); Azure CLI locally."""

    client_id = identity.managedIdentityClientId or None
    if environ.get("IDENTITY_ENDPOINT") or environ.get("MSI_ENDPOINT"):
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential(managed_identity_client_id=client_id)


class TokenProvider:
    """Caches one access token per scope until shortly before it expires (refresh margin from identity config)."""

    def __init__(
        self,
        credential: Any,
        scope: str,
        *,
        refresh_margin_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._credential = credential
        self._scope = scope
        self._margin = refresh_margin_seconds
        self._clock = clock
        self._token: str | None = None
        self._expires_on = 0.0
        self._lock = threading.Lock()

    @property
    def scope(self) -> str:
        return self._scope

    def token(self) -> str:
        with self._lock:
            if self._token is None or self._expires_on - self._margin <= self._clock():
                try:
                    access = self._credential.get_token(self._scope)
                except Exception as exc:  # the credential SDK raises several unrelated types
                    raise UpstreamError(
                        "Identity",
                        f"could not acquire a token for scope {self._scope}. "
                        "Check the managed identity or the Azure CLI sign-in.",
                        code="identity_unavailable",
                        status_code=503,
                    ) from exc
                self._token = access.token
                self._expires_on = float(access.expires_on)
            return self._token


def _backoff_delay(attempt: int, backoff: float, cap: float) -> float:
    return min(backoff * (2**attempt), cap)


def _retry_after_delay(response: httpx.Response, attempt: int, backoff: float, cap: float) -> float:
    """Honors Retry-After (seconds or HTTP-date); falls back to exponential backoff."""

    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(max(float(header), 0.0), cap)
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(header)
                return min(max(when.timestamp() - time.time(), 0.0), cap)
            except (TypeError, ValueError):
                pass
    return _backoff_delay(attempt, backoff, cap)


class UpstreamHttp:
    """httpx client wrapper: bearer header per attempt, retries for throttling and transient failures."""

    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None,
        timeout_seconds: float,
        max_retries: int,
        backoff_seconds: float,
        max_delay_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.service = service
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        tokens: TokenProvider | None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            request_headers = dict(headers or {})
            if tokens is not None:
                request_headers["Authorization"] = f"Bearer {tokens.token()}"
            try:
                response = self._client.request(
                    method, url, headers=request_headers, params=params, json=json_body
                )
            except httpx.TimeoutException as exc:
                if attempt >= self._max_retries:
                    raise UpstreamError(
                        self.service, "the request timed out", code="upstream_timeout", status_code=504
                    ) from exc
                self._sleep(_backoff_delay(attempt, self._backoff, self._max_delay))
                attempt += 1
                continue
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise UpstreamError(
                        self.service, "the service could not be reached", code="upstream_unreachable", status_code=502
                    ) from exc
                self._sleep(_backoff_delay(attempt, self._backoff, self._max_delay))
                attempt += 1
                continue
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep(_retry_after_delay(response, attempt, self._backoff, self._max_delay))
                attempt += 1
                continue
            return response

    def close(self) -> None:
        self._client.close()


def upstream_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, dict):
            message = message.get("value")
        if message:
            return str(message)[:240]
        if error.get("code"):
            return str(error["code"])[:240]
    return ""


def check_response(service: str, response: httpx.Response) -> None:
    """Translate a failed upstream response into the API's error model. Never includes tokens."""

    status = response.status_code
    if status < 400:
        return
    if status == 404:
        raise UpstreamNotFoundError(service, "the requested resource was not found")
    detail = upstream_detail(response)
    suffix = f" ({detail})" if detail else ""
    if status in (401, 403):
        raise UpstreamError(
            service,
            "access was denied. Check the application permissions granted to the managed identity" + suffix,
            code="upstream_forbidden",
            status_code=502,
        )
    if status == 429:
        headers = {"Retry-After": response.headers["Retry-After"]} if "Retry-After" in response.headers else None
        raise UpstreamError(
            service, "is throttling requests; try again later", code="upstream_throttled", status_code=503,
            headers=headers,
        )
    if status >= 500:
        raise UpstreamError(service, f"returned HTTP {status}{suffix}", code="upstream_unavailable", status_code=502)
    raise UpstreamError(service, f"rejected the request (HTTP {status}){suffix}", code="upstream_bad_request",
                        status_code=502)
