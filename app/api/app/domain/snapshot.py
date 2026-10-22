"""Library snapshot: every item of one library with its inheritance state and effective permission entries.

Role assignments are loaded lazily per securable object and cached. Inheritance follows SharePoint's rule:
an item uses its own assignments when it has unique permissions, otherwise the nearest ancestor folder with
unique permissions, otherwise the library when the library is unique, otherwise the site.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from app.clients.sharepoint import SharePointClient
from app.domain.documents import parse_datetime, parse_governance
from app.domain.identity import (
    SITE_ITEM_ID,
    compose_item_id,
    is_within,
    lower_key,
    parent_path,
    web_url,
)
from app.domain.permissions import PermissionEntry, SourceRef, entries_from_assignments
from app.domain.principals import PrincipalClassifier
from app.core.governance import Governance

SITE_SOURCE = "site"
LIBRARY_SOURCE = "library"
FOLDER_TYPE = 1


@dataclass(frozen=True)
class LibraryInfo:
    id: str
    title: str
    root_path: str
    unique: bool


@dataclass
class ItemRecord:
    library_id: str
    list_item_id: int
    unique_id: str | None
    kind: str
    name: str
    path: str
    unique: bool
    created: datetime | None
    modified: datetime | None
    size: int | None
    child_count: int | None
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def item_id(self) -> str:
        return compose_item_id(self.library_id, self.list_item_id)

    @property
    def source_key(self) -> str:
        return f"item:{self.list_item_id}"

    @property
    def parent(self) -> str:
        return parent_path(self.path)


def item_from_row(row: Mapping[str, Any], *, library: LibraryInfo, governance: Governance) -> ItemRecord:
    path = str(row.get("FileRef") or "")
    kind = "folder" if row.get("FileSystemObjectType") == FOLDER_TYPE else "file"
    name = str(row.get("FileLeafRef") or path.rsplit("/", 1)[-1])
    file_info = row.get("File") or {}
    folder_info = row.get("Folder") or {}
    size = file_info.get("Length") if isinstance(file_info, Mapping) else None
    child_count = folder_info.get("ItemCount") if isinstance(folder_info, Mapping) else None
    return ItemRecord(
        library_id=library.id,
        list_item_id=int(row["Id"]),
        unique_id=row.get("UniqueId"),
        kind=kind,
        name=name,
        path=path,
        unique=bool(row.get("HasUniqueRoleAssignments")),
        created=parse_datetime(row.get("Created")),
        modified=parse_datetime(row.get("Modified")),
        size=int(size) if size is not None else None,
        child_count=int(child_count) if child_count is not None else None,
        fields=parse_governance(row, governance),
    )


class LibrarySnapshot:
    def __init__(
        self,
        library: LibraryInfo,
        items: Iterable[ItemRecord],
        *,
        sharepoint: SharePointClient,
        classifier: PrincipalClassifier,
        origin: str,
        site_path: str,
        load_ancestor: Callable[[str], ItemRecord | None],
        truncated: bool,
        warnings: list[str],
        clock: Callable[[], float],
    ) -> None:
        self.library = library
        self.items: list[ItemRecord] = list(items)
        self.truncated = truncated
        self.warnings = list(warnings)
        self.fetched_at = clock()
        self._sp = sharepoint
        self._classifier = classifier
        self._origin = origin
        self._site_path = site_path
        self._load_ancestor = load_ancestor
        self._by_path: dict[str, ItemRecord] = {lower_key(item.path): item for item in self.items}
        self._by_id: dict[str, ItemRecord] = {item.item_id: item for item in self.items}
        self._assignments: dict[str, list[dict[str, Any]]] = {}
        self._entries: dict[str, list[PermissionEntry]] = {}
        self._lock = threading.RLock()

    @property
    def files(self) -> list[ItemRecord]:
        return [item for item in self.items if item.kind == "file"]

    @property
    def folders(self) -> list[ItemRecord]:
        return [item for item in self.items if item.kind == "folder"]

    def by_id(self, item_id: str) -> ItemRecord | None:
        return self._by_id.get(item_id)

    def register(self, item: ItemRecord) -> None:
        with self._lock:
            self._by_path.setdefault(lower_key(item.path), item)
            self._by_id.setdefault(item.item_id, item)

    def _ancestor(self, path: str) -> ItemRecord | None:
        key = lower_key(path)
        known = self._by_path.get(key)
        if known is not None:
            return known
        loaded = self._load_ancestor(path)
        if loaded is not None:
            self.register(loaded)
        return loaded

    def source_for(self, item: ItemRecord) -> tuple[str, bool, SourceRef]:
        """Returns (source key, inherited?, reference to the source). Inherited sources are ancestors or containers."""

        if item.unique:
            return item.source_key, False, SourceRef(item.item_id, item.path, "item")
        root = self.library.root_path
        current = item.parent
        while is_within(current, root) and lower_key(current) != lower_key(root):
            ancestor = self._ancestor(current)
            if ancestor is not None and ancestor.unique:
                return ancestor.source_key, True, SourceRef(ancestor.item_id, ancestor.path, "item")
            current = parent_path(current)
        if self.library.unique:
            return LIBRARY_SOURCE, True, SourceRef(self.library.id, self.library.root_path, "library")
        return SITE_SOURCE, True, SourceRef(SITE_ITEM_ID, self._site_path, "site")

    def assignments(self, source_key: str) -> list[dict[str, Any]]:
        with self._lock:
            if source_key in self._assignments:
                return self._assignments[source_key]
        if source_key == SITE_SOURCE:
            rows = self._sp.role_assignments("web")
        elif source_key == LIBRARY_SOURCE:
            rows = self._sp.role_assignments(self._sp.list_path(self.library.id))
        else:
            list_item_id = int(source_key.split(":", 1)[1])
            rows = self._sp.role_assignments(f"{self._sp.list_path(self.library.id)}/items({list_item_id})")
        with self._lock:
            self._assignments[source_key] = rows
        return rows

    def entries_for(self, item: ItemRecord) -> list[PermissionEntry]:
        with self._lock:
            cached = self._entries.get(item.item_id)
        if cached is not None:
            return cached
        source_key, inherited, source = self.source_for(item)
        entries = entries_from_assignments(
            self.assignments(source_key),
            self._classifier,
            inherited_from=source if inherited else None,
        )
        with self._lock:
            self._entries[item.item_id] = entries
        return entries

    def container_entries(self) -> dict[str, list[PermissionEntry]]:
        """Entries held directly at the library root and at the site, as reported to exposure analysis."""

        result: dict[str, list[PermissionEntry]] = {}
        if self.library.unique:
            result[LIBRARY_SOURCE] = entries_from_assignments(
                self.assignments(LIBRARY_SOURCE), self._classifier, inherited_from=None
            )
        result[SITE_SOURCE] = entries_from_assignments(
            self.assignments(SITE_SOURCE), self._classifier, inherited_from=None
        )
        return result

    def library_entries(self) -> tuple[list[PermissionEntry], SourceRef | None]:
        """Effective entries of the library root: its own, or the site's when the library inherits."""

        if self.library.unique:
            return (
                entries_from_assignments(self.assignments(LIBRARY_SOURCE), self._classifier, inherited_from=None),
                None,
            )
        source = SourceRef(SITE_ITEM_ID, self._site_path, "site")
        return (
            entries_from_assignments(self.assignments(SITE_SOURCE), self._classifier, inherited_from=source),
            source,
        )

    def inheritance_source(self, item: ItemRecord) -> SourceRef | None:
        _, inherited, source = self.source_for(item)
        return source if inherited else None

    def absolute_url(self, server_relative_path: str) -> str:
        return web_url(self._origin, server_relative_path)
