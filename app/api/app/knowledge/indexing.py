"""Indexing visibility for a published artifact: published -> indexing -> available to AI.

The existing SharePoint indexer (one per hub, hourly by default) is the only ingestion path. This module never writes
to the index. It can start an indexer run, read the indexer status and check whether the artifact is already in the
index. DemoIndexing simulates the same stages from elapsed time when no Search service is configured.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import httpx

from app.clients.transport import TokenProvider, UpstreamHttp, check_response
from app.core.config import KnowledgeIndexingConfig
from app.core.errors import ApiError, UpstreamError
from app.knowledge.models import ARTIFACT_ID_PATTERN, IndexingStatus

SEARCH_SERVICE = "Azure AI Search"
STAGE_DEMO_PUBLISHED_SHARE = 0.15
SUCCESS_RUN = "success"
FAILED_RUNS = frozenset({"transientFailure", "persistentFailure"})


class IndexingProvider(Protocol):
    mode: str

    def status(self, artifact_id: str, *, published_at: datetime, ai_ready: bool) -> IndexingStatus: ...

    def trigger(self, artifact_id: str, *, published_at: datetime, ai_ready: bool) -> IndexingStatus: ...


def now_iso(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SearchIndexing:
    mode = "search"

    def __init__(
        self,
        config: KnowledgeIndexingConfig,
        *,
        site_id: str,
        endpoint: str,
        tokens: TokenProvider,
        transport: httpx.BaseTransport | None,
        timeout_seconds: float,
        max_retries: int,
        backoff_seconds: float,
        max_delay_seconds: float,
        sleep: Callable[[float], None],
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._indexer = config.indexerTemplate.replace("{siteId}", site_id)
        self._alias = config.indexAliasBySiteId.get(site_id, config.defaultIndexAlias)
        self._endpoint = endpoint.rstrip("/")
        self._tokens = tokens
        self._clock = clock
        self._http = UpstreamHttp(
            SEARCH_SERVICE, self._endpoint, transport=transport, timeout_seconds=timeout_seconds,
            max_retries=max_retries, backoff_seconds=backoff_seconds, max_delay_seconds=max_delay_seconds, sleep=sleep,
        )

    @property
    def indexer(self) -> str:
        return self._indexer

    def _params(self) -> dict[str, str]:
        return {"api-version": self._config.apiVersion}

    def trigger(self, artifact_id: str, *, published_at: datetime, ai_ready: bool) -> IndexingStatus:
        response = self._http.request(
            "POST", f"{self._endpoint}/indexers/{self._indexer}/run", tokens=self._tokens, params=self._params()
        )
        if response.status_code == 409:
            return self.status(artifact_id, published_at=published_at, ai_ready=ai_ready)
        if response.status_code in (401, 403):
            raise UpstreamError(
                SEARCH_SERVICE,
                "the API's managed identity may not run the indexer. Grant it 'Search Service Contributor' on the "
                "Search service, or wait for the scheduled run.",
                code="indexer_run_denied",
                status_code=502,
            )
        if response.status_code == 404:
            raise UpstreamError(
                SEARCH_SERVICE, f"the indexer '{self._indexer}' was not found. Check indexing.indexerTemplate.",
                code="indexer_not_found", status_code=502,
            )
        check_response(SEARCH_SERVICE, response)
        return self.status(artifact_id, published_at=published_at, ai_ready=ai_ready, run_requested=True)

    def status(
        self, artifact_id: str, *, published_at: datetime, ai_ready: bool, run_requested: bool = False
    ) -> IndexingStatus:
        checked = now_iso(self._clock)
        if not ARTIFACT_ID_PATTERN.match(artifact_id):
            raise UpstreamError(SEARCH_SERVICE, "invalid artifact id", code="bad_request", status_code=400)
        if not ai_ready:
            return self._build("notReady", "Published to SharePoint, but not AI-ready, so the AI will not use it yet.", checked)
        try:
            indexer = self._read_indexer_status()
            found = self._in_index(artifact_id)
        except ApiError as exc:
            return self._build("failed", f"Indexing status could not be read. {exc.message}", checked)
        if found:
            return self._build("available", "Available to AI. The existing agent can now cite this document.", checked)
        last = indexer.get("lastResult") or {}
        started = parse_time(last.get("startTime"))
        ran_after_publish = started is not None and started >= published_at
        running = indexer.get("status") == "running" or last.get("status") == "inProgress"
        elapsed = (self._clock() - published_at).total_seconds()
        if ran_after_publish and last.get("status") in FAILED_RUNS:
            reason = str(last.get("errorMessage") or "the indexer run failed")[:240]
            return self._build("failed", f"The indexer reported a failure: {reason}. Check the indexer in Azure AI Search.", checked)
        if elapsed > self._config.expectedDelaySeconds and not running:
            return self._build("delayed", f"Indexing is taking longer than expected. {self._config.scheduleHint}", checked)
        if running or ran_after_publish or run_requested:
            return self._build("indexing", "Indexing. The SharePoint indexer is processing the new document.", checked)
        return self._build("published", f"Published to SharePoint. {self._config.scheduleHint}", checked)

    def _build(self, stage: str, message: str, checked: str) -> IndexingStatus:
        return IndexingStatus(stage=stage, message=message, mode=self.mode, indexer=self._indexer, checkedAt=checked,
                              canTrigger=stage in ("published", "delayed", "failed"))

    def _read_indexer_status(self) -> dict[str, Any]:
        response = self._http.request(
            "GET", f"{self._endpoint}/indexers/{self._indexer}/status", tokens=self._tokens, params=self._params()
        )
        check_response(SEARCH_SERVICE, response)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _in_index(self, artifact_id: str) -> bool:
        """True when the artifact is already searchable. Where the identity may not query the index, this is False."""

        response = self._http.request(
            "POST",
            f"{self._endpoint}/indexes/{self._alias}/docs/search",
            tokens=self._tokens,
            params=self._params(),
            json_body={"search": "*", "filter": f"artifact_id eq '{artifact_id}'", "top": 1, "select": "artifact_id"},
        )
        if response.status_code in (401, 403, 404):
            return False
        check_response(SEARCH_SERVICE, response)
        payload = response.json()
        return bool(isinstance(payload, dict) and payload.get("value"))


class DemoIndexing:
    """Simulated stages, driven only by elapsed time. Clearly reported as demo mode."""

    mode = "demo"

    def __init__(self, config: KnowledgeIndexingConfig, *, clock: Callable[[], datetime]) -> None:
        self._seconds = config.demoIndexingSeconds
        self._clock = clock

    def status(self, artifact_id: str, *, published_at: datetime, ai_ready: bool) -> IndexingStatus:
        checked = now_iso(self._clock)
        if not ai_ready:
            return IndexingStatus(stage="notReady", mode=self.mode, checkedAt=checked, canTrigger=False,
                                  message="Demo mode: published, but not AI-ready, so the AI would not use it yet.")
        elapsed = (self._clock() - published_at).total_seconds()
        if elapsed >= self._seconds:
            return IndexingStatus(stage="available", mode=self.mode, checkedAt=checked, canTrigger=False,
                                  message="Demo mode: available to AI (indexing is simulated).")
        if elapsed >= self._seconds * STAGE_DEMO_PUBLISHED_SHARE:
            return IndexingStatus(stage="indexing", mode=self.mode, checkedAt=checked, canTrigger=False,
                                  message="Demo mode: indexing (simulated).")
        return IndexingStatus(stage="published", mode=self.mode, checkedAt=checked, canTrigger=False,
                              message="Demo mode: published. Indexing starts shortly (simulated).")

    def trigger(self, artifact_id: str, *, published_at: datetime, ai_ready: bool) -> IndexingStatus:
        return self.status(artifact_id, published_at=published_at, ai_ready=ai_ready)


def search_endpoint(config: KnowledgeIndexingConfig) -> str | None:
    if not config.serviceName or re.search(r"[<>{}]", config.serviceName):
        return None
    return config.endpointTemplate.replace("{serviceName}", config.serviceName)
