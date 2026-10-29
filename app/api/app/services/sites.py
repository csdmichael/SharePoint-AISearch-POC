"""Site overview, configured libraries, lazy folder children and per-item permissions."""

from __future__ import annotations

from itertools import islice
from typing import Any

from app.clients.sharepoint import SharePointClient, odata_string
from app.core.config import Settings
from app.core.errors import BadRequestError, NotFoundError, UpstreamError, UpstreamNotFoundError
from app.domain.identity import is_system_path, split_item_id, web_url
from app.domain.permissions import PermissionEntry
from app.domain.principals import PrincipalKind
from app.domain.snapshot import LibraryInfo
from app.services.corpus import LibraryCorpus
from app.services.library import LibraryService
from app.services.membership import Member, MembershipService
from app.services.views import entry_view, item_view, library_view

FOLDER_TYPE = 1
CHILD_SELECT: tuple[str, ...] = (
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
CHILD_EXPAND: tuple[str, ...] = ("Folder", "File")


class SiteService:
    def __init__(
        self,
        *,
        settings: Settings,
        sharepoint: SharePointClient,
        libraries: LibraryService,
        membership: MembershipService,
        origin: str,
    ) -> None:
        self._settings = settings
        self._sharepoint = sharepoint
        self._libraries = libraries
        self._membership = membership
        self._origin = origin
        self._site_path = settings.site.server_relative_path

    def info(self) -> dict[str, Any]:
        web = self._sharepoint.web()
        selected = self._settings.site
        available = [
            {
                "siteId": site.site_id,
                "displayName": site.display_name,
                "function": site.function,
                "siteUrl": site.site_url,
                "serverRelativeUrl": site.server_relative_path,
            }
            for site in self._settings.site_catalog
        ]
        return {
            "name": web.get("Title"),
            "webUrl": web.get("Url"),
            "serverRelativeUrl": web.get("ServerRelativeUrl"),
            "hasUniquePermissions": bool(web.get("HasUniqueRoleAssignments")),
            "libraryCount": len(self._libraries.configured()),
            "selectedSite": {
                "siteId": selected.site_id,
                "displayName": selected.display_name,
                "function": selected.function,
                "siteUrl": selected.site_url,
                "serverRelativeUrl": selected.server_relative_path,
            },
            "availableSites": available,
        }

    def libraries(self) -> dict[str, Any]:
        items = [
            {
                "id": library.id,
                "libraryId": library.id,
                "title": library.title,
                "rootPath": library.root_path,
                "webUrl": web_url(self._origin, library.root_path),
                "hasUniquePermissions": library.unique,
            }
            for library in self._libraries.configured()
        ]
        return {"items": items, "total": len(items)}

    def children(self, library_id: str, folder_id: str | None) -> dict[str, Any]:
        library = self._libraries.find(library_id)
        folder_view: dict[str, Any] | None = None
        parent_path = library.root_path
        if folder_id:
            folder_library, folder_item_id = split_item_id(folder_id)
            if folder_library != library.id or folder_item_id is None:
                raise BadRequestError("folderId must identify a folder inside this library.")
            try:
                row = self._sharepoint.item(library.id, folder_item_id, select=list(CHILD_SELECT),
                                            expand=list(CHILD_EXPAND))
            except UpstreamNotFoundError as exc:
                raise NotFoundError("The folder was not found in the library.") from exc
            if int(row.get("FileSystemObjectType", -1)) != FOLDER_TYPE:
                raise BadRequestError("folderId must identify a folder, not a file.")
            parent_path = str(row["FileRef"])
            folder_view = self._child_view(library, row)
        limit = self._settings.api.sharePoint.crawl.maxItems
        rows = list(islice(
            self._sharepoint.list_items(
                library.id,
                select=list(CHILD_SELECT),
                expand=list(CHILD_EXPAND),
                filter_text=f"FileDirRef eq {odata_string(parent_path)}",
            ),
            limit + 1,
        ))
        truncated = len(rows) > limit
        system_names = tuple(self._settings.api.sharePoint.systemFolderNames)
        children = [
            self._child_view(library, row)
            for row in rows[:limit]
            if not is_system_path(str(row.get("FileRef") or ""), library.root_path, system_names)
        ]
        children.sort(key=lambda child: (child["kind"] != "folder", child["name"].lower()))
        return {
            "library": {"id": library.id, "title": library.title, "rootPath": library.root_path},
            "folder": folder_view,
            "items": children,
            "total": len(children),
            "truncated": truncated,
        }

    def _child_view(self, library: LibraryInfo, row: dict[str, Any]) -> dict[str, Any]:
        path = str(row.get("FileRef") or "")
        kind = "folder" if int(row.get("FileSystemObjectType", 0)) == FOLDER_TYPE else "file"
        folder_info = row.get("Folder") or {}
        file_info = row.get("File") or {}
        return {
            "id": f"{library.id}.{int(row['Id'])}",
            "libraryId": library.id,
            "name": str(row.get("FileLeafRef") or path.rsplit("/", 1)[-1]),
            "kind": kind,
            "path": path,
            "webUrl": web_url(self._origin, path),
            "hasUniquePermissions": bool(row.get("HasUniqueRoleAssignments")),
            "childCount": folder_info.get("ItemCount") if kind == "folder" else None,
            "size": file_info.get("Length") if kind == "file" else None,
            "modified": row.get("Modified"),
            "created": row.get("Created"),
        }

    def permissions(self, item_id: str) -> dict[str, Any]:
        entries_error: str | None = None
        library_id, list_item_id = split_item_id(item_id)
        if list_item_id is None:
            library = self._libraries.find(library_id)
            corpus = self._libraries.corpus(library.id)
            try:
                entries, source = corpus.snapshot.library_entries()
            except UpstreamError as exc:
                entries, source = [], None
                entries_error = exc.message
            subject = library_view(corpus, self._origin)
            link_entries = corpus.links(None, container=True)
            link_error = corpus.link_error("library", container=True)
            unique = library.unique
        else:
            corpus, item = self._libraries.item(item_id)
            try:
                entries = corpus.snapshot.entries_for(item)
                source = corpus.snapshot.inheritance_source(item)
            except UpstreamError as exc:
                entries = []
                source = None
                entries_error = exc.message
            subject = item_view(corpus, item)
            link_entries = corpus.links(item)
            link_error = corpus.link_error(item.item_id)
            unique = item.unique
        return self._permission_payload(
            corpus, subject, entries + link_entries, source, unique, link_error, entries_error
        )

    def _permission_payload(
        self,
        corpus: LibraryCorpus,
        subject: dict[str, Any],
        entries: list[PermissionEntry],
        source: Any,
        unique: bool,
        link_error: str | None,
        entries_error: str | None,
    ) -> dict[str, Any]:
        views: list[dict[str, Any]] = []
        for entry in entries:
            members: list[dict[str, Any]] = []
            account: dict[str, Any] | None = None
            principal = entry.principal
            if principal.is_group:
                members = [member.to_json() for member in self._membership.members(principal)]
            elif principal.kind is PrincipalKind.SHARING_LINK and entry.grantees:
                members = [self._grantee(upn) for upn in entry.grantees]
            if principal.kind is PrincipalKind.USER and principal.upn:
                enabled, status = self._membership.account(principal.upn)
                account = {"accountEnabled": enabled, "status": status}
            views.append(entry_view(entry, members, account))
        warnings: list[dict[str, str]] = []
        if entries_error:
            warnings.append(
                {"code": "roleAssignmentsUnavailable", "message": f"Role assignments could not be read: {entries_error}"}
            )
        if link_error:
            warnings.append({"code": "sharingLinksUnavailable",
                             "message": f"Sharing links could not be read: {link_error}"})
        for warning in corpus.snapshot.warnings:
            warnings.append({"code": "crawlTruncated", "message": warning})
        return {
            "item": subject,
            "inheritance": {
                "hasUniquePermissions": unique,
                "source": source.to_json() if source is not None and not unique else None,
            },
            "entries": views,
            "warnings": warnings,
        }

    def _grantee(self, upn: str) -> dict[str, Any]:
        enabled, status = self._membership.account(upn)
        return Member(None, upn, upn, enabled, status).to_json()
