"""Configured libraries, the TTL'd per-library corpus cache, and snapshot construction from SharePoint rows."""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.parse import urlsplit

from app.clients.graph import GraphClient
from app.clients.sharepoint import SharePointClient
from app.core.config import Settings
from app.core.errors import NotFoundError, UpstreamError, UpstreamNotFoundError
from app.core.governance import Governance
from app.domain.documents import governance_select
from app.domain.identity import is_system_path, is_within, lower_key, path_depth, split_item_id
from app.domain.principals import PrincipalClassifier
from app.domain.snapshot import ItemRecord, LibraryInfo, LibrarySnapshot, item_from_row
from app.services.corpus import LibraryCorpus

SYSTEM_LIBRARY_TITLES: frozenset[str] = frozenset(
    {
        "form templates",
        "site assets",
        "style library",
        "agent assets",
        "site pages",
        "maintenance log library",
    }
)

BASE_SELECT: tuple[str, ...] = (
    "Id",
    "UniqueId",
    "FileSystemObjectType",
    "FileRef",
    "FileDirRef",
    "FileLeafRef",
    "Title",
    "Modified",
    "Created",
    "HasUniqueRoleAssignments",
    "File/Length",
    "Folder/ItemCount",
)
BASE_EXPAND: tuple[str, ...] = ("Folder", "File")


def origin_of(site_url: str) -> str:
    parts = urlsplit(site_url)
    return f"{parts.scheme}://{parts.netloc}"


class LibraryService:
    def __init__(
        self,
        *,
        settings: Settings,
        governance: Governance,
        sharepoint: SharePointClient,
        graph: GraphClient,
        classifier: PrincipalClassifier,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._governance = governance
        self._sharepoint = sharepoint
        self._graph = graph
        self._classifier = classifier
        self._clock = clock
        self._ttl = settings.api.cache.libraryTtlSeconds
        self._libraries: tuple[float, list[LibraryInfo]] | None = None
        self._corpora: dict[str, tuple[float, LibraryCorpus]] = {}
        self._lock = threading.RLock()
        self._origin = origin_of(settings.site.site_url)
        self._site_path = urlsplit(settings.site.site_url).path
        governance_columns, governance_expand = governance_select(governance)
        self._select = list(BASE_SELECT) + governance_columns
        self._expand = list(BASE_EXPAND) + governance_expand

    @property
    def origin(self) -> str:
        return self._origin

    def configured(self) -> list[LibraryInfo]:
        with self._lock:
            now = self._clock()
            if self._libraries is not None and now - self._libraries[0] < self._ttl:
                return list(self._libraries[1])
            wanted = {name.lower() for name in self._settings.api.sharePoint.libraryDisplayNames}
            found: list[LibraryInfo] = []
            for row in self._sharepoint.libraries():
                title = str(row.get("Title") or "")
                if wanted:
                    if title.lower() not in wanted:
                        continue
                elif title.lower() in SYSTEM_LIBRARY_TITLES:
                    continue
                root = (row.get("RootFolder") or {}).get("ServerRelativeUrl") or ""
                found.append(
                    LibraryInfo(
                        id=str(row["Id"]).lower(),
                        title=title,
                        root_path=str(root),
                        unique=bool(row.get("HasUniqueRoleAssignments")),
                    )
                )
            found.sort(key=lambda info: info.title.lower())
            self._libraries = (now, found)
            return list(found)

    def find(self, library_id: str) -> LibraryInfo:
        for info in self.configured():
            if info.id == library_id.lower():
                return info
        raise NotFoundError(f"Library {library_id} is not configured for this API.")

    def corpus(self, library_id: str) -> LibraryCorpus:
        info = self.find(library_id)
        with self._lock:
            now = self._clock()
            cached = self._corpora.get(info.id)
            if cached is not None and now - cached[0] < self._ttl:
                return cached[1]
            corpus = LibraryCorpus(
                library=info,
                snapshot=self._build_snapshot(info),
                graph=self._graph,
                settings=self._settings,
                origin=self._origin,
                workers=self._settings.api.graph.maxConcurrency,
            )
            self._corpora[info.id] = (now, corpus)
            return corpus

    def item(self, item_id: str) -> tuple[LibraryCorpus, ItemRecord]:
        """Resolves a composite item id to its corpus and record, fetching from SharePoint when not in the snapshot."""

        library_id, list_item_id = split_item_id(item_id)
        if list_item_id is None:
            raise NotFoundError("The identifier names a library, not an item.")
        corpus = self.corpus(library_id)
        known = corpus.snapshot.by_id(item_id)
        if known is not None:
            return corpus, known
        try:
            row = self._sharepoint.item(
                corpus.library.id, list_item_id, select=self._select, expand=self._expand
            )
        except UpstreamNotFoundError as exc:
            raise NotFoundError(f"Item {item_id} was not found in the library.") from exc
        record = item_from_row(row, library=corpus.library, governance=self._governance)
        if not is_within(record.path, corpus.library.root_path):
            raise NotFoundError(f"Item {item_id} is outside the configured library.")
        corpus.snapshot.register(record)
        return corpus, record

    def _build_snapshot(self, info: LibraryInfo) -> LibrarySnapshot:
        crawl = self._settings.api.sharePoint.crawl
        system_names = tuple(self._settings.api.sharePoint.systemFolderNames)
        items: list[ItemRecord] = []
        truncated = False
        warnings: list[str] = []
        try:
            raw_rows = list(self._sharepoint.list_items(info.id, select=self._select, expand=self._expand))
        except UpstreamError as exc:
            if exc.code != "upstream_bad_request":
                raise
            raw_rows = list(self._sharepoint.list_items(info.id, select=list(BASE_SELECT), expand=list(BASE_EXPAND)))
            warnings.append(f"Governance columns not present on library '{info.title}'.")

        for row in raw_rows:
            path = str(row.get("FileRef") or "")
            if not is_within(path, info.root_path) or lower_key(path) == lower_key(info.root_path):
                continue
            if is_system_path(path, info.root_path, system_names):
                continue
            if path_depth(path, info.root_path) > crawl.maxDepth:
                truncated = True
                continue
            if len(items) >= crawl.maxItems:
                truncated = True
                break
            items.append(item_from_row(row, library=info, governance=self._governance))
        if truncated:
            warnings.append(
                f"The crawl stopped at {crawl.maxItems} items or {crawl.maxDepth} folder levels; results are partial."
            )

        def load_ancestor(path: str) -> ItemRecord | None:
            try:
                row = self._sharepoint.folder_item(path, select=self._select, expand=self._expand)
            except UpstreamNotFoundError:
                return None
            except UpstreamError as exc:
                if exc.code != "upstream_bad_request":
                    raise
                row = self._sharepoint.folder_item(path, select=list(BASE_SELECT), expand=list(BASE_EXPAND))
            return item_from_row(row, library=info, governance=self._governance)

        return LibrarySnapshot(
            info,
            items,
            sharepoint=self._sharepoint,
            classifier=self._classifier,
            origin=self._origin,
            site_path=self._site_path,
            load_ancestor=load_ancestor,
            truncated=truncated,
            warnings=warnings,
            clock=self._clock,
        )
