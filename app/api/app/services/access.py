"""Site users and the by-user access index: every item a user can reach, with the role and grant path."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.clients.sharepoint import SharePointClient
from app.core.config import Settings
from app.core.errors import UpstreamError
from app.domain.permissions import PermissionEntry
from app.domain.principals import PrincipalKind
from app.services.corpus import LibraryCorpus
from app.services.library import LibraryService
from app.services.membership import MembershipService
from app.services.views import item_view

ANY_USER = "all"
INTERNAL_USER = "internal"


@dataclass
class AccessIndex:
    direct: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    wildcards: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def add(self, user: str, record: dict[str, Any]) -> None:
        self.direct.setdefault(user, []).append(record)

    def for_user(self, user: str, *, external: bool) -> list[dict[str, Any]]:
        records = list(self.direct.get(user, []))
        for scope, record in self.wildcards:
            if scope == ANY_USER or (scope == INTERNAL_USER and not external):
                records.append(record)
        return records


def _record_key(record: dict[str, Any]) -> tuple[Any, ...]:
    inherited = record["inheritedFrom"]["path"] if record["inheritedFrom"] else None
    return (record["item"]["id"], record["role"], record["grantedVia"], tuple(record["via"]), inherited)


class AccessService:
    def __init__(
        self,
        *,
        settings: Settings,
        sharepoint: SharePointClient,
        libraries: LibraryService,
        membership: MembershipService,
        user_pattern: re.Pattern[str],
        external_pattern: re.Pattern[str],
    ) -> None:
        self._settings = settings
        self._sharepoint = sharepoint
        self._libraries = libraries
        self._membership = membership
        self._user_pattern = user_pattern
        self._external_pattern = external_pattern
        exposure = settings.analytics.exposure
        self._anonymous = frozenset(exposure.anonymousLinkScopes)
        self._organization = frozenset(exposure.organizationLinkScopes)

    def is_external(self, user_key: str) -> bool:
        return self._external_pattern.search(user_key) is not None

    def search_users(self, query: str, limit: int) -> dict[str, Any]:
        needle = query.strip().lower()
        max_scan = self._settings.api.sharePoint.maxSiteUsers
        users: list[dict[str, Any]] = []
        scanned = 0
        scan_limited = False
        for row in self._sharepoint.site_users():
            scanned += 1
            if scanned > max_scan:
                scan_limited = True
                break
            login = str(row.get("LoginName") or "")
            match = self._user_pattern.search(login)
            if match is None and row.get("PrincipalType") != 1:
                continue
            upn_value = (match.group("upn") if match and "upn" in match.re.groupindex and match.group("upn")
                         else row.get("UserPrincipalName"))
            upn = str(upn_value).lower() if upn_value else None
            display = str(row.get("Title") or upn or login)
            email = row.get("Email") or None
            haystack = " ".join(str(part or "") for part in (display, upn, email, login)).lower()
            if needle and needle not in haystack:
                continue
            users.append({
                "userKey": upn or login.lower(),
                "displayName": display,
                "userPrincipalName": upn,
                "email": email,
                "loginName": login,
                "external": self.is_external(upn or login),
            })
            if len(users) >= limit:
                break
        return {"query": query, "users": users, "scanned": scanned, "scanLimited": scan_limited}

    def build_index(self, corpus: LibraryCorpus) -> AccessIndex:
        return corpus.memo("access-index", lambda: self._build(corpus))

    def _build(self, corpus: LibraryCorpus) -> AccessIndex:
        index = AccessIndex()
        items = corpus.snapshot.items
        corpus.prefetch_links(items)
        for item in items:
            view = item_view(corpus, item)
            entries: list[PermissionEntry] = []
            role_assignments_unavailable = False
            try:
                entries.extend(corpus.snapshot.entries_for(item))
            except UpstreamError:
                role_assignments_unavailable = True
            if role_assignments_unavailable:
                try:
                    entries.extend(corpus.graph_entries(item))
                except UpstreamError:
                    continue
            else:
                try:
                    entries.extend(corpus.links(item))
                except UpstreamError:
                    pass
            for entry in entries:
                self._index_entry(index, view, entry)
        return index

    def _index_entry(self, index: AccessIndex, view: dict[str, Any], entry: PermissionEntry) -> None:
        principal = entry.principal
        if principal.kind is PrincipalKind.USER and principal.upn:
            index.add(principal.upn, self._record(view, entry, via=()))
        elif principal.is_group:
            for member in self._membership.members(principal):
                if member.upn:
                    index.add(member.upn, self._record(view, entry, via=(principal.display_name,)))
        elif principal.kind is PrincipalKind.CLAIMS:
            scope = ANY_USER if principal.claim_scope == "includingExternal" else INTERNAL_USER
            index.wildcards.append((scope, self._record(view, entry, via=())))
        elif principal.kind is PrincipalKind.SHARING_LINK:
            if entry.link_scope in self._anonymous:
                index.wildcards.append((ANY_USER, self._record(view, entry, via=())))
            elif entry.link_scope in self._organization:
                index.wildcards.append((INTERNAL_USER, self._record(view, entry, via=())))
            else:
                for upn in entry.grantees:
                    index.add(upn, self._record(view, entry, via=()))

    @staticmethod
    def _record(view: dict[str, Any], entry: PermissionEntry, *, via: tuple[str, ...]) -> dict[str, Any]:
        return {
            "item": view,
            "role": entry.role,
            "grantedVia": entry.granted_via,
            "via": list(via),
            "inheritedFrom": entry.inherited_from.to_json() if entry.inherited_from else None,
            "linkScope": entry.link_scope,
        }

    def records_for(self, user_key: str) -> list[dict[str, Any]]:
        key = user_key.strip().lower()
        external = self.is_external(key)
        seen: set[tuple[Any, ...]] = set()
        records: list[dict[str, Any]] = []
        for library in self._libraries.configured():
            corpus = self._libraries.corpus(library.id)
            for record in self.build_index(corpus).for_user(key, external=external):
                marker = _record_key(record)
                if marker not in seen:
                    seen.add(marker)
                    records.append(record)
        return records

    def user_items(
        self,
        user_key: str,
        *,
        role: str | None,
        granted_via: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        key = user_key.strip().lower()
        records = self.records_for(key)
        if role:
            wanted = role.strip().lower()
            records = [record for record in records if wanted in record["role"].lower()]
        if granted_via:
            records = [record for record in records if record["grantedVia"] == granted_via]
        records.sort(key=lambda record: (record["item"]["path"].lower(), record["grantedVia"], record["role"]))
        total = len(records)
        start = (page - 1) * page_size
        return {
            "user": {"userKey": key, "external": self.is_external(key)},
            "items": records[start:start + page_size],
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, -(-total // page_size)),
        }
