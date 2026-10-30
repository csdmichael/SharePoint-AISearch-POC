"""Live publishing and indexing clients against a recording mock of Microsoft Graph, SharePoint and Azure AI Search."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
import pytest

from app.clients.graph import GraphClient
from app.clients.sharepoint import SharePointClient
from app.clients.transport import TokenProvider, UpstreamHttp
from app.core.config import KnowledgeIndexingConfig, KnowledgePublishConfig, Settings, SiteSettings, load_settings
from app.core.errors import ApiError
from app.knowledge.indexing import DemoIndexing, SearchIndexing
from app.knowledge.publisher import ArtifactPackage, GraphPublisher
from tests.helpers.settings import write_config

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
ARTIFACT = "KNW-ABCD1234"
GRAPH = "https://graph.microsoft.com/v1.0"
LIST_ID = "11111111-2222-3333-4444-555555555555"
SITE = "https://contoso.sharepoint.com/sites/knowledge"


class Credential:
    def get_token(self, *_: Any, **__: Any) -> Any:
        return type("Token", (), {"token": "t", "expires_on": 4102444800})()


class Recorder:
    def __init__(self, columns: list[str] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, tuple[int, dict[str, Any]]] = {}
        self.existing_names: set[str] = set()
        self.columns = columns

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        for needle, (status, body) in self.fail.items():
            if needle in key:
                return httpx.Response(status, json=body)
        path = request.url.path
        if path.endswith("/lists") and "/sites/" in path:
            return httpx.Response(200, json={"value": [{"id": LIST_ID, "displayName": "Documents"}]})
        if path.endswith("/drive"):
            return httpx.Response(200, json={"id": "drive-1", "name": "Documents"})
        if "/sites/contoso.sharepoint.com" in path:
            return httpx.Response(200, json={"id": "site-1", "displayName": "Knowledge Hub"})
        if path.endswith("/fields") and path.startswith("/sites/knowledge/_api"):
            names = self.columns if self.columns is not None else ALL_COLUMNS
            return httpx.Response(200, json={"value": [{"InternalName": name} for name in names]})
        if path.endswith("/ensureuser"):
            return httpx.Response(200, json={"Id": 42})
        if request.method == "PUT" and path.endswith(":/content"):
            name = path.split("root:/", 1)[1].removesuffix(":/content")
            if name.rsplit("/", 1)[-1] in self.existing_names:
                return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
            return httpx.Response(201, json={"id": "item-1", "name": name.rsplit("/", 1)[-1],
                                             "webUrl": f"{SITE}/Shared%20Documents/{name}"})
        if request.method == "PATCH" and path.endswith("/listItem/fields"):
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": "unexpected " + key}})


ALL_COLUMNS = ["Title", "ArtifactId", "KnowledgeCategory", "SourceTable", "SourceSystem", "KnowledgeOwner",
               "OwnerDisplayName", "LifecycleStatus", "DocumentIteration", "Authoritative", "ReviewDate",
               "DocumentType", "ProcessArea", "Sensitivity", "EffectiveDate", "BusinessUnit", "ProductFamily",
               "AIReady", "TrustScore", "DataQualityStatus", "ConflictStatus", "ConflictWith", "DuplicateOf",
               "ContentHash", "TrustReasons", "LastValidatedDate"]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return load_settings(write_config(tmp_path), env={})


def build_publisher(settings: Settings, recorder: Recorder) -> GraphPublisher:
    transport = httpx.MockTransport(recorder)
    site: SiteSettings = settings.site
    tokens = TokenProvider(Credential(), "scope", refresh_margin_seconds=0)
    graph_http = UpstreamHttp("Microsoft Graph", GRAPH, transport=transport, timeout_seconds=5, max_retries=0,
                              backoff_seconds=0, max_delay_seconds=0, sleep=lambda _: None)
    sp_http = UpstreamHttp("SharePoint", site.site_url, transport=transport, timeout_seconds=5, max_retries=0,
                           backoff_seconds=0, max_delay_seconds=0, sleep=lambda _: None)
    return GraphPublisher(
        config=settings.knowledge.publish, governance=settings.governance, site=site,
        graph=GraphClient(GRAPH, http=graph_http, tokens=tokens, page_size=50),
        sharepoint=SharePointClient(site.site_url, http=sp_http, tokens=tokens, page_size=50),
    )


def package(settings: Settings) -> ArtifactPackage:
    fields = {"Title": "Workaround", "ArtifactId": ARTIFACT, "LifecycleStatus": "Published", "Authoritative": True,
              "AIReady": True, "AutomationOnly": "x"}
    return ArtifactPackage(ARTIFACT, "Workaround.docx", b"docx-bytes", "# md", fields, "owner@contoso.com", {})


def test_a_publish_uploads_then_writes_metadata_and_resolves_the_owner(settings: Settings) -> None:
    recorder = Recorder()
    published = build_publisher(settings, recorder).publish(package(settings))
    methods = [(r.method, r.url.path) for r in recorder.requests]
    assert ("PUT", "/v1.0/drives/drive-1/root:/Knowledge Capture/Workaround.docx:/content") in methods
    assert any(r.url.params.get("@microsoft.graph.conflictBehavior") == "fail" for r in recorder.requests if r.method == "PUT")
    patch = next(r for r in recorder.requests if r.method == "PATCH")
    sent = json.loads(patch.content)
    assert sent["KnowledgeOwnerLookupId"] == 42 and sent["AIReady"] is True and sent["LifecycleStatus"] == "Published"
    assert "AutomationOnly" not in sent
    assert published.skipped_fields == ["AutomationOnly"]
    assert published.web_url and published.web_url.startswith(SITE)
    assert published.mode == "graph"


def test_a_missing_governance_column_stops_the_publish_before_any_upload(settings: Settings) -> None:
    recorder = Recorder(columns=["Title", "ArtifactId"])
    with pytest.raises(ApiError) as caught:
        build_publisher(settings, recorder).publish(package(settings))
    assert caught.value.code == "library_not_governed" and caught.value.status_code == 422
    assert "Add-GovernanceColumnsToLibrary.ps1" in caught.value.message
    assert not any(r.method == "PUT" for r in recorder.requests)


def test_a_title_clash_retries_once_with_the_artifact_id(settings: Settings) -> None:
    recorder = Recorder()
    recorder.existing_names = {"Workaround.docx"}
    published = build_publisher(settings, recorder).publish(package(settings))
    assert published.file_name == f"Workaround ({ARTIFACT}).docx"


def test_when_both_names_clash_the_user_is_asked_to_change_the_title(settings: Settings) -> None:
    recorder = Recorder()
    recorder.existing_names = {"Workaround.docx", f"Workaround ({ARTIFACT}).docx"}
    with pytest.raises(ApiError) as caught:
        build_publisher(settings, recorder).publish(package(settings))
    assert caught.value.code == "document_exists"


def test_write_access_denied_names_the_permission_to_grant(settings: Settings) -> None:
    recorder = Recorder()
    recorder.fail["PUT"] = (403, {"error": {"code": "accessDenied"}})
    with pytest.raises(ApiError) as caught:
        build_publisher(settings, recorder).publish(package(settings))
    assert caught.value.code == "sharepoint_write_denied"
    assert "Sites.Selected" in caught.value.message


def test_a_metadata_failure_removes_the_uploaded_document(settings: Settings) -> None:
    recorder = Recorder()
    recorder.fail["PATCH"] = (400, {"error": {"code": "invalidRequest", "message": "bad choice value"}})
    with pytest.raises(ApiError) as caught:
        build_publisher(settings, recorder).publish(package(settings))
    assert caught.value.code == "sharepoint_metadata_failed"
    assert "removed again" in caught.value.message and "bad choice value" in caught.value.message
    assert any(r.method == "DELETE" for r in recorder.requests)


def test_an_unknown_library_is_a_configuration_error(settings: Settings, tmp_path) -> None:
    config = write_config(tmp_path / "other", knowledge={"publish": {"libraryName": "Nope"}})
    other = load_settings(config, env={})
    with pytest.raises(ApiError) as caught:
        build_publisher(other, Recorder()).publish(package(other))
    assert caught.value.code == "library_not_found"


def test_an_oversized_document_is_refused(settings: Settings, tmp_path) -> None:
    other = load_settings(write_config(tmp_path / "small", knowledge={"publish": {"maxDocumentBytes": 1024}}), env={})
    big = ArtifactPackage(ARTIFACT, "Workaround.docx", b"x" * 2048, "", {}, "o@contoso.com", {})
    with pytest.raises(ApiError) as caught:
        build_publisher(other, Recorder()).publish(big)
    assert caught.value.code == "document_too_large"


# ---- indexing -----------------------------------------------------------------------------------------------------

SEARCH = "https://search-test.search.windows.net"


class SearchMock:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.indexer: dict[str, Any] = {"status": "running", "lastResult": None}
        self.docs: list[dict[str, Any]] = []
        self.run_status = 202
        self.doc_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.url.path.endswith("/run"):
            return httpx.Response(self.run_status, json={})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=self.indexer)
        if request.url.path.endswith("/docs/search"):
            assert json.loads(request.content)["filter"] == f"artifact_id eq '{ARTIFACT}'"
            return httpx.Response(self.doc_status, json={"value": self.docs})
        return httpx.Response(404, json={})


def build_indexing(settings: Settings, mock: SearchMock, now: datetime = NOW) -> SearchIndexing:
    config: KnowledgeIndexingConfig = settings.knowledge.indexing
    return SearchIndexing(
        config, site_id="manufacturing", endpoint=SEARCH, tokens=TokenProvider(Credential(), "s", refresh_margin_seconds=0),
        transport=httpx.MockTransport(mock), timeout_seconds=5, max_retries=0, backoff_seconds=0, max_delay_seconds=0,
        sleep=lambda _: None, clock=lambda: now,
    )


def test_the_artifact_is_available_once_it_is_in_the_index(settings: Settings) -> None:
    mock = SearchMock()
    mock.docs = [{"artifact_id": ARTIFACT}]
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW - timedelta(minutes=2), ai_ready=True)
    assert status.stage == "available" and status.indexer == "manufacturing-sp-indexer" and status.mode == "search"


def test_a_running_indexer_reads_as_indexing(settings: Settings) -> None:
    status = build_indexing(settings, SearchMock()).status(ARTIFACT, published_at=NOW - timedelta(minutes=1), ai_ready=True)
    assert status.stage == "indexing"


def test_before_any_run_it_is_published_and_can_be_triggered(settings: Settings) -> None:
    mock = SearchMock()
    mock.indexer = {"status": "idle", "lastResult": {"status": "success", "startTime": (NOW - timedelta(hours=1)).isoformat()}}
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW - timedelta(minutes=1), ai_ready=True)
    assert status.stage == "published" and status.canTrigger is True


def test_a_failed_run_after_publishing_is_reported(settings: Settings) -> None:
    mock = SearchMock()
    mock.indexer = {"status": "idle", "lastResult": {"status": "transientFailure", "errorMessage": "skill timeout",
                                                      "startTime": NOW.isoformat()}}
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW - timedelta(minutes=1), ai_ready=True)
    assert status.stage == "failed" and "skill timeout" in status.message


def test_indexing_that_takes_too_long_is_reported_as_delayed(settings: Settings) -> None:
    mock = SearchMock()
    mock.indexer = {"status": "idle", "lastResult": {"status": "success", "startTime": (NOW - timedelta(hours=3)).isoformat()}}
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW - timedelta(hours=1), ai_ready=True)
    assert status.stage == "delayed"


def test_content_that_is_not_ai_ready_is_never_reported_as_available(settings: Settings) -> None:
    mock = SearchMock()
    mock.docs = [{"artifact_id": ARTIFACT}]
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW, ai_ready=False)
    assert status.stage == "notReady"
    assert mock.calls == []


def test_a_search_outage_is_reported_instead_of_raising(settings: Settings) -> None:
    mock = SearchMock()
    mock.doc_status = 500
    status = build_indexing(settings, mock).status(ARTIFACT, published_at=NOW, ai_ready=True)
    assert status.stage == "failed" and "Azure AI Search" in status.message


def test_triggering_the_indexer_runs_it_and_reports_indexing(settings: Settings) -> None:
    mock = SearchMock()
    mock.indexer = {"status": "idle", "lastResult": None}
    status = build_indexing(settings, mock).trigger(ARTIFACT, published_at=NOW, ai_ready=True)
    assert ("POST", "/indexers/manufacturing-sp-indexer/run") in mock.calls
    assert status.stage == "indexing"


def test_an_indexer_that_is_already_running_is_not_an_error(settings: Settings) -> None:
    mock = SearchMock()
    mock.run_status = 409
    assert build_indexing(settings, mock).trigger(ARTIFACT, published_at=NOW, ai_ready=True).stage == "indexing"


@pytest.mark.parametrize(("status", "code"), [(403, "indexer_run_denied"), (404, "indexer_not_found")])
def test_trigger_failures_say_what_to_fix(settings: Settings, status: int, code: str) -> None:
    mock = SearchMock()
    mock.run_status = status
    with pytest.raises(ApiError) as caught:
        build_indexing(settings, mock).trigger(ARTIFACT, published_at=NOW, ai_ready=True)
    assert caught.value.code == code


def test_demo_indexing_follows_elapsed_time(settings: Settings) -> None:
    config = settings.knowledge.indexing
    for seconds, stage in [(0, "published"), (5, "indexing"), (12, "available")]:
        clock: Callable[[], datetime] = lambda s=seconds: NOW + timedelta(seconds=s)
        assert DemoIndexing(config, clock=clock).status(ARTIFACT, published_at=NOW, ai_ready=True).stage == stage
