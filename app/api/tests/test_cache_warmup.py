"""Corpus rebuilds reuse extracted text until a file's content tag changes; hygiene and the warmer reuse memory."""

from __future__ import annotations

import threading
import time
from typing import Any, Iterator

import pytest
from azure.core.credentials import AccessToken
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.container import Container
from app.container_manager import ContainerManager
from app.core.config import CacheConfig, Settings
from app.services.hygiene import HygieneService
from app.services.warmer import CacheWarmer
from tests.helpers.fake_tenant import DEFAULT_LIBRARY_TITLE, FakeTenant


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StaticCredential:
    def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken(f"token-for:{scopes[0]}", int(time.time()) + 3600)


def content_downloads(tenant: FakeTenant) -> list[str]:
    return [url for method, url in tenant.calls if method == "GET" and url.endswith("/content")]


def fixture_key(tenant: FakeTenant, library_id: str, list_item_id: int) -> str:
    return tenant.library_by_id(library_id)["items"][list_item_id - 1]["key"]


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def container(tenant: FakeTenant, settings: Settings, clock: ManualClock) -> Iterator[Container]:
    built = Container(settings, transport=tenant.transport(), credential=StaticCredential(),
                      sleep=lambda _seconds: None, clock=clock)
    yield built
    built.close()


@pytest.fixture
def library_id(container: Container) -> str:
    return next(lib.id for lib in container.libraries.configured() if lib.title == DEFAULT_LIBRARY_TITLE)


def test_rebuilt_corpus_reuses_text_of_unchanged_files(
    container: Container, tenant: FakeTenant, clock: ManualClock, settings: Settings, library_id: str
) -> None:
    corpus = container.libraries.corpus(library_id)
    corpus.prefetch_text(corpus.snapshot.files)
    downloaded = content_downloads(tenant)
    assert downloaded

    clock.advance(settings.api.cache.libraryTtlSeconds + 1)
    rebuilt = container.libraries.corpus(library_id)
    assert rebuilt is not corpus
    rebuilt.prefetch_text(rebuilt.snapshot.files)

    assert content_downloads(tenant) == downloaded


def test_edited_file_is_downloaded_again_and_nothing_else(
    container: Container, tenant: FakeTenant, clock: ManualClock, settings: Settings, library_id: str
) -> None:
    corpus = container.libraries.corpus(library_id)
    corpus.prefetch_text(corpus.snapshot.files)
    before = len(content_downloads(tenant))
    edited = next(item for item in corpus.snapshot.files if corpus.text(item).status == "ok")
    key = fixture_key(tenant, library_id, edited.list_item_id)
    tenant.bump_content(key)

    clock.advance(settings.api.cache.libraryTtlSeconds + 1)
    rebuilt = container.libraries.corpus(library_id)
    rebuilt.prefetch_text(rebuilt.snapshot.files)

    new_downloads = content_downloads(tenant)[before:]
    assert len(new_downloads) == 1
    assert new_downloads[0].endswith(f"/items/drv-{key}/content")


def test_failed_download_is_not_cached(
    container: Container, tenant: FakeTenant, clock: ManualClock, settings: Settings, library_id: str
) -> None:
    corpus = container.libraries.corpus(library_id)
    corpus.prefetch_text(corpus.snapshot.files)
    target = next(item for item in corpus.snapshot.files if corpus.text(item).status == "ok")
    key = fixture_key(tenant, library_id, target.list_item_id)
    tenant.bump_content(key)
    tenant.add_rule(contains=f"drv-{key}/content", status=500, times=1)

    clock.advance(settings.api.cache.libraryTtlSeconds + 1)
    failed = container.libraries.corpus(library_id).text(target)
    assert failed.status == "error"

    clock.advance(1)
    retried = container.libraries.corpus(library_id, fresh=True).text(target)
    assert retried.status == "ok"


def test_fresh_corpus_rebuilds_once_and_later_reads_reuse_it(
    container: Container, clock: ManualClock, library_id: str
) -> None:
    first = container.libraries.corpus(library_id)
    assert container.libraries.corpus(library_id) is first

    clock.advance(1)
    refreshed = container.libraries.corpus(library_id, fresh=True)
    assert refreshed is not first
    assert container.libraries.corpus(library_id) is refreshed


def test_hygiene_model_is_reused_until_refreshed_or_expired(
    container: Container, settings: Settings, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    hygiene = HygieneService(settings=settings, governance=settings.governance, libraries=container.libraries,
                             analytics=container.analytics, clock=clock)
    builds: list[int] = []
    original_build = hygiene._build

    def counted_build() -> Any:
        builds.append(1)
        return original_build()

    monkeypatch.setattr(hygiene, "_build", counted_build)
    hygiene.summary()
    hygiene.summary()
    assert len(builds) == 1

    clock.advance(1)
    hygiene.refresh()
    assert len(builds) == 2

    clock.advance(settings.api.cache.libraryTtlSeconds + 1)
    hygiene.summary()
    assert len(builds) == 3


def test_warmer_leaves_every_site_warm_for_the_next_request(
    tenant: FakeTenant, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ContainerManager(settings, transport=tenant.transport(), credential=StaticCredential(),
                               sleep=lambda _seconds: None)
    try:
        outcomes = CacheWarmer(manager, interval_seconds=240).warm_once()
        assert outcomes == {site_id: "ok" for site_id in manager.site_ids()}

        hygiene = manager.for_site(manager.site_ids()[0]).hygiene
        builds: list[int] = []
        original_build = hygiene._build
        monkeypatch.setattr(hygiene, "_build", lambda: (builds.append(1), original_build())[1])
        hygiene.summary()
        assert builds == []
    finally:
        manager.close()


def test_warmer_records_a_failing_site_and_keeps_going(
    tenant: FakeTenant, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ContainerManager(settings, transport=tenant.transport(), credential=StaticCredential(),
                               sleep=lambda _seconds: None)
    try:
        def unreachable(_selector: str | None) -> Any:
            raise RuntimeError("sharepoint unreachable")

        monkeypatch.setattr(manager, "for_site", unreachable)
        outcomes = CacheWarmer(manager, interval_seconds=240).warm_once()
        assert outcomes == {site_id: "RuntimeError" for site_id in manager.site_ids()}
    finally:
        manager.close()


def test_warm_interval_must_be_shorter_than_the_library_ttl() -> None:
    with pytest.raises(ValidationError):
        CacheConfig(libraryTtlSeconds=300, membershipTtlSeconds=900, warmIntervalSeconds=300)
    assert CacheConfig(libraryTtlSeconds=300, membershipTtlSeconds=900).warmIntervalSeconds == 0


def test_app_starts_no_warmer_unless_asked(build_app: Any, settings: Settings) -> None:
    with TestClient(build_app(settings)):
        assert not [thread for thread in threading.enumerate() if thread.name == "cache-warmer"]
