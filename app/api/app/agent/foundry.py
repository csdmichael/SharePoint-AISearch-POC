"""Microsoft Foundry Responses API client. Used only when Foundry is configured; the evidence is sent as grounding."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from app.clients.transport import TokenProvider, UpstreamHttp, check_response
from app.core.config import FoundryTarget
from app.core.errors import UpstreamError

FOUNDRY_SERVICE = "Microsoft Foundry"


def output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


class FoundryClient:
    def __init__(
        self,
        target: FoundryTarget,
        *,
        tokens: TokenProvider,
        max_retry_delay_seconds: float,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not target.endpoint or not target.agent_name:
            raise ValueError("Foundry client requires an endpoint and an agent name")
        self._endpoint = target.endpoint.rstrip("/")
        self._path = target.responses_path.lstrip("/")
        self._agent = target.agent_name
        self._tokens = tokens
        self._http = UpstreamHttp(
            FOUNDRY_SERVICE,
            self._endpoint,
            transport=transport,
            timeout_seconds=target.timeout_seconds,
            max_retries=target.max_retries,
            backoff_seconds=target.retry_backoff_seconds,
            max_delay_seconds=max_retry_delay_seconds,
            sleep=sleep,
        )

    def respond(self, text_input: str) -> str:
        response = self._http.request(
            "POST",
            f"{self._endpoint}/{self._path}",
            tokens=self._tokens,
            json_body={
                "input": text_input,
                "agent_reference": {"type": "agent_reference", "name": self._agent},
            },
        )
        check_response(FOUNDRY_SERVICE, response)
        try:
            payload = response.json()
        except ValueError:
            raise UpstreamError(FOUNDRY_SERVICE, "returned a payload that is not JSON") from None
        if not isinstance(payload, dict):
            raise UpstreamError(FOUNDRY_SERVICE, "returned an unexpected payload")
        text = output_text(payload)
        if not text:
            raise UpstreamError(FOUNDRY_SERVICE, "returned no text output")
        return text

    def close(self) -> None:
        self._http.close()
