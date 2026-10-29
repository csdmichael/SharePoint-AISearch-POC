"""Per-library corpus: the SharePoint snapshot plus lazily cached Graph data (sharing links, content text)
and memoized analysis results. A corpus lives for the library cache TTL, so every answer is live data
no older than that TTL.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Hashable, Iterable, TypeVar

from app.analytics.text import extract_text, normalize_text
from app.clients.graph import GraphClient
from app.core.config import Settings
from app.core.errors import UpstreamError
from app.domain.identity import compose_item_id, file_extension
from app.domain.permissions import GRANT_INHERITED, GRANT_SHARING_LINK, PermissionEntry, SourceRef, grant_mechanism
from app.domain.principals import Principal, PrincipalKind
from app.domain.snapshot import ItemRecord, LibraryInfo, LibrarySnapshot

T = TypeVar("T")
LINK_CLAIM_SCOPES = frozenset({"anonymous", "organization", "users"})


@dataclass(frozen=True)
class TextResult:
    status: str
    text: str | None = None
    reason: str | None = None


@dataclass
class DriveContext:
    site_id: str
    drive_id: str
    by_list_id: dict[int, dict[str, Any]]
    list_by_drive_item: dict[str, int]


class LibraryCorpus:
    def __init__(
        self,
        *,
        library: LibraryInfo,
        snapshot: LibrarySnapshot,
        graph: GraphClient,
        settings: Settings,
        origin: str,
        workers: int,
    ) -> None:
        self.library = library
        self.snapshot = snapshot
        self._graph = graph
        self._settings = settings
        self._origin = origin
        self._workers = max(1, workers)
        self._drive: DriveContext | None = None
        self._links: dict[str, list[PermissionEntry]] = {}
        self._link_errors: dict[str, str] = {}
        self._graph_entries: dict[str, list[PermissionEntry]] = {}
        self._graph_entry_errors: dict[str, str] = {}
        self._texts: dict[str, TextResult] = {}
        self._identities: dict[str, str | None] = {}
        self._memo: dict[Hashable, Any] = {}
        self._lock = threading.RLock()

    @property
    def library_id(self) -> str:
        return self.library.id

    def memo(self, key: Hashable, factory: Callable[[], T]) -> T:
        with self._lock:
            if key in self._memo:
                return self._memo[key]
        value = factory()
        with self._lock:
            self._memo[key] = value
        return value

    def drive_context(self) -> DriveContext:
        with self._lock:
            if self._drive is not None:
                return self._drive
            try:
                site = self._settings.site
                graph_site = self._graph.site(site.host, site.server_relative_path)
                site_id = str(graph_site["id"])
                drive = self._graph.library_drive(site_id, self.library.id)
                by_list: dict[int, dict[str, Any]] = {}
                reverse: dict[str, int] = {}
                for row in self._graph.list_drive_items(site_id, self.library.id):
                    drive_item = row.get("driveItem")
                    if isinstance(drive_item, dict) and drive_item.get("id") and row.get("id") is not None:
                        list_item_id = int(row["id"])
                        by_list[list_item_id] = drive_item
                        reverse[str(drive_item["id"])] = list_item_id
                self._drive = DriveContext(site_id=site_id, drive_id=str(drive["id"]), by_list_id=by_list,
                                           list_by_drive_item=reverse)
            except UpstreamError as exc:
                self._drive = DriveContext(site_id="", drive_id="", by_list_id={}, list_by_drive_item={})
                self._link_errors["library"] = exc.message
            return self._drive

    # ---- sharing links -------------------------------------------------------------------------------------

    def links(self, item: ItemRecord | None, *, container: bool = False) -> list[PermissionEntry]:
        key = "library" if container else item.item_id  # type: ignore[union-attr]
        with self._lock:
            if key in self._links:
                return self._links[key]
        try:
            entries = self._fetch_links(item, container=container)
        except UpstreamError as exc:
            with self._lock:
                self._link_errors[key] = exc.message
            entries = []
        with self._lock:
            self._links[key] = entries
        return entries

    def link_error(self, item_id: str, *, container: bool = False) -> str | None:
        return self._link_errors.get("library" if container else item_id)

    def graph_entries(self, item: ItemRecord | None, *, container: bool = False) -> list[PermissionEntry]:
        key = "library" if container else item.item_id  # type: ignore[union-attr]
        with self._lock:
            if key in self._graph_entries:
                return self._graph_entries[key]
        try:
            entries = self._fetch_graph_entries(item, container=container)
        except UpstreamError as exc:
            with self._lock:
                self._graph_entry_errors[key] = exc.message
            entries = []
        with self._lock:
            self._graph_entries[key] = entries
        return entries

    def graph_entry_error(self, item_id: str, *, container: bool = False) -> str | None:
        return self._graph_entry_errors.get("library" if container else item_id)

    def _fetch_graph_entries(self, item: ItemRecord | None, *, container: bool) -> list[PermissionEntry]:
        context = self.drive_context()
        if not context.drive_id:
            return []
        if container:
            permissions = self._graph.drive_root_permissions(context.drive_id)
        else:
            assert item is not None
            drive_item = context.by_list_id.get(item.list_item_id)
            if drive_item is None:
                return []
            permissions = self._graph.drive_item_permissions(context.drive_id, str(drive_item["id"]))
        entries: list[PermissionEntry] = []
        for permission in permissions:
            inherited_from = self._inherited_from(permission.get("inheritedFrom"), context)
            roles = self._permission_roles(permission)
            link = permission.get("link")
            if isinstance(link, dict):
                scope = str(link.get("scope") or "users")
                link_type = str(link.get("type") or "view")
                grantees = tuple(
                    sorted(
                        {
                            upn
                            for identity in permission.get("grantedToIdentitiesV2") or []
                            if (upn := self._identity_upn(identity))
                        }
                    )
                )
                principal = Principal(
                    kind=PrincipalKind.SHARING_LINK,
                    key=f"link:{permission.get('id')}",
                    display_name=self._settings.analytics.exposure.linkLabels.get(scope, scope),
                )
                entries.append(
                    PermissionEntry(
                        principal=principal,
                        roles=(self._link_role(link_type),),
                        granted_via=GRANT_SHARING_LINK,
                        inherited_from=inherited_from,
                        link_scope=scope,
                        link_type=link_type,
                        grantees=grantees,
                    )
                )
                continue
            for principal in self._permission_principals(permission):
                entries.append(
                    PermissionEntry(
                        principal=principal,
                        roles=roles,
                        granted_via=GRANT_INHERITED if inherited_from is not None else grant_mechanism(principal.kind),
                        inherited_from=inherited_from,
                    )
                )
        return entries

    def _fetch_links(self, item: ItemRecord | None, *, container: bool) -> list[PermissionEntry]:
        context = self.drive_context()
        if not context.drive_id:
            return []
        if container:
            permissions = self._graph.drive_root_permissions(context.drive_id)
        else:
            assert item is not None
            drive_item = context.by_list_id.get(item.list_item_id)
            if drive_item is None:
                return []
            permissions = self._graph.drive_item_permissions(context.drive_id, str(drive_item["id"]))
        entries: list[PermissionEntry] = []
        for permission in permissions:
            link = permission.get("link")
            if not isinstance(link, dict):
                continue
            scope = str(link.get("scope") or "users")
            link_type = str(link.get("type") or "view")
            grantees = tuple(
                sorted({upn for identity in permission.get("grantedToIdentitiesV2") or []
                        if (upn := self._identity_upn(identity))})
            )
            principal = Principal(
                kind=PrincipalKind.SHARING_LINK,
                key=f"link:{permission.get('id')}",
                display_name=self._settings.analytics.exposure.linkLabels.get(scope, scope),
            )
            entries.append(
                PermissionEntry(
                    principal=principal,
                    roles=(self._link_role(link_type),),
                    granted_via=GRANT_SHARING_LINK,
                    inherited_from=self._inherited_from(permission.get("inheritedFrom"), context),
                    link_scope=scope,
                    link_type=link_type,
                    grantees=grantees,
                )
            )
        return entries

    def _permission_roles(self, permission: dict[str, Any]) -> tuple[str, ...]:
        roles = permission.get("roles")
        if isinstance(roles, list):
            named = tuple(str(role).strip() for role in roles if isinstance(role, str) and role.strip())
            if named:
                return named
        return ("Unspecified",)

    def _permission_principals(self, permission: dict[str, Any]) -> list[Principal]:
        identities: list[dict[str, Any]] = []
        single = permission.get("grantedToV2")
        if isinstance(single, dict):
            identities.append(single)
        multi = permission.get("grantedToIdentitiesV2")
        if isinstance(multi, list):
            identities.extend(identity for identity in multi if isinstance(identity, dict))
        principals: list[Principal] = []
        seen: set[tuple[PrincipalKind, str]] = set()
        for identity in identities:
            principal = self._principal_from_identity(identity)
            if principal is None:
                continue
            key = (principal.kind, principal.identifier)
            if key in seen:
                continue
            seen.add(key)
            principals.append(principal)
        return principals

    def _principal_from_identity(self, identity: dict[str, Any]) -> Principal | None:
        site_group = identity.get("siteGroup")
        if isinstance(site_group, dict):
            raw_id = site_group.get("id")
            sp_id = None
            if isinstance(raw_id, int):
                sp_id = raw_id
            elif isinstance(raw_id, str) and raw_id.isdigit():
                sp_id = int(raw_id)
            display = str(site_group.get("displayName") or site_group.get("loginName") or "Unknown SharePoint group")
            login = site_group.get("loginName")
            return Principal(
                kind=PrincipalKind.SHAREPOINT_GROUP,
                key=f"spgroup:{sp_id if sp_id is not None else display.lower()}",
                display_name=display,
                login_name=str(login) if login else None,
                sp_principal_id=sp_id,
            )
        user = identity.get("siteUser")
        if not isinstance(user, dict):
            user = identity.get("user")
        if isinstance(user, dict):
            upn_raw = user.get("userPrincipalName") or user.get("email") or user.get("id")
            upn = str(upn_raw).lower() if upn_raw else None
            display = str(user.get("displayName") or upn or "Unknown user")
            email_raw = user.get("email")
            email = str(email_raw).lower() if email_raw else (upn if upn and "@" in upn else None)
            return Principal(
                kind=PrincipalKind.USER,
                key=f"user:{upn or display.lower()}",
                display_name=display,
                login_name=upn,
                email=email,
                upn=upn,
            )
        group = identity.get("group")
        if isinstance(group, dict):
            group_id_raw = group.get("id")
            group_id = str(group_id_raw).lower() if group_id_raw else None
            display = str(group.get("displayName") or group_id or "Unknown Entra group")
            return Principal(
                kind=PrincipalKind.ENTRA_GROUP,
                key=f"entra:{group_id or display.lower()}",
                display_name=display,
                login_name=group_id,
                entra_group_id=group_id,
            )
        return None

    def _link_role(self, link_type: str) -> str:
        sharepoint = self._settings.api.sharePoint
        return sharepoint.linkRoleNames.get(link_type, sharepoint.defaultLinkRole)

    def _identity_upn(self, identity: Any) -> str | None:
        user = identity.get("user") if isinstance(identity, dict) else None
        if not isinstance(user, dict):
            return None
        direct = user.get("userPrincipalName") or user.get("email")
        if direct:
            return str(direct).lower()
        object_id = user.get("id")
        if not object_id:
            return None
        with self._lock:
            if object_id in self._identities:
                return self._identities[object_id]
        try:
            account = self._graph.user(str(object_id))
        except UpstreamError:
            account = None
        upn = str(account["userPrincipalName"]).lower() if account and account.get("userPrincipalName") else None
        with self._lock:
            self._identities[str(object_id)] = upn
        return upn

    def _inherited_from(self, inherited: Any, context: DriveContext) -> SourceRef | None:
        if not isinstance(inherited, dict) or not inherited:
            return None
        list_item_id = context.list_by_drive_item.get(str(inherited.get("id") or ""))
        if list_item_id is None:
            return SourceRef(self.library.id, self.library.root_path, "library")
        source = self.snapshot.by_id(compose_item_id(self.library.id, list_item_id))
        path = source.path if source else str(inherited.get("path") or "")
        return SourceRef(compose_item_id(self.library.id, list_item_id), path, "item")

    # ---- content text --------------------------------------------------------------------------------------

    def text(self, item: ItemRecord) -> TextResult:
        with self._lock:
            cached = self._texts.get(item.item_id)
        if cached is not None:
            return cached
        try:
            result = self._load_text(item)
        except UpstreamError as exc:
            result = TextResult("error", reason=exc.message)
        except Exception as exc:
            result = TextResult("error", reason=str(exc))
        with self._lock:
            self._texts[item.item_id] = result
        return result

    def _load_text(self, item: ItemRecord) -> TextResult:
        extraction = self._settings.analytics.extraction
        extension = file_extension(item.name)
        if extension not in extraction.supportedExtensions:
            return TextResult("unsupported", reason=f"{extension or 'no extension'} is not analyzed")
        if item.size is not None and item.size > extraction.maxFileBytes:
            return TextResult("tooLarge", reason="file exceeds the analysis size limit")
        context = self.drive_context()
        if not context.drive_id:
            return TextResult("noDrive", reason="drive is not available")
        drive_item = context.by_list_id.get(item.list_item_id)
        if drive_item is None:
            return TextResult("noDriveItem", reason="no drive item is linked to this list item")
        try:
            content = self._graph.drive_item_content(context.drive_id, str(drive_item["id"]))
        except UpstreamError as exc:
            return TextResult("error", reason=exc.message)
        if len(content) > extraction.maxFileBytes:
            return TextResult("tooLarge", reason="file exceeds the analysis size limit")
        try:
            raw = extract_text(extension, content)
        except Exception as exc:  # parsers raise many unrelated exception types for damaged files
            return TextResult("unreadable", reason=type(exc).__name__)
        normalized = normalize_text(raw, self._settings.governance.similarity["whitespacePattern"])
        if not normalized:
            return TextResult("empty", reason="no text content")
        return TextResult("ok", text=normalized)

    # ---- bulk prefetch -------------------------------------------------------------------------------------

    def prefetch_links(self, items: Iterable[ItemRecord]) -> None:
        pending = [item for item in items if item.item_id not in self._links]
        if not pending:
            return
        context = self.drive_context()
        if not context.drive_id:
            return
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            list(pool.map(self.links, pending))

    def prefetch_text(self, items: Iterable[ItemRecord]) -> None:
        pending = [item for item in items if item.item_id not in self._texts]
        if not pending:
            return
        context = self.drive_context()
        if not context.drive_id:
            return
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            list(pool.map(self.text, pending))

    def web_url(self, item_path: str) -> str:
        return self.snapshot.absolute_url(item_path)
