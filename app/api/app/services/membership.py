"""Group expansion and account state, cached with a TTL.

Entra groups expand through Graph transitiveMembers (users only). SharePoint groups expand through the site
group's user list. Every user's account state comes from Graph users/{upn}: enabled, disabled or missing.
Failures are reported as 'unknown' members instead of silently dropping the group.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Hashable, TypeVar

from app.clients.graph import GraphClient
from app.clients.sharepoint import SharePointClient
from app.core.errors import UpstreamError
from app.domain.principals import Principal, PrincipalKind

T = TypeVar("T")
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"
STATUS_MISSING = "missing"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Member:
    id: str | None
    display_name: str
    upn: str | None
    account_enabled: bool | None
    status: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "userPrincipalName": self.upn,
            "accountEnabled": self.account_enabled,
            "status": self.status,
        }


def _status(enabled: bool | None) -> str:
    if enabled is None:
        return STATUS_UNKNOWN
    return STATUS_ENABLED if enabled else STATUS_DISABLED


class MembershipService:
    def __init__(
        self,
        *,
        graph: GraphClient,
        sharepoint: SharePointClient,
        user_pattern: re.Pattern[str],
        ttl_seconds: int,
        max_members: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._graph = graph
        self._sharepoint = sharepoint
        self._user_pattern = user_pattern
        self._ttl = ttl_seconds
        self._max_members = max_members
        self._clock = clock
        self._cache: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def _cached(self, key: Hashable, loader: Callable[[], T]) -> T:
        with self._lock:
            now = self._clock()
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
        value = loader()
        with self._lock:
            if self._ttl > 0:
                self._cache[key] = (now, value)
        return value

    def members(self, principal: Principal) -> list[Member]:
        if principal.kind is PrincipalKind.ENTRA_GROUP and principal.entra_group_id:
            group_id = principal.entra_group_id
            return self._cached(("entra", group_id), lambda: self._entra_members(group_id))
        if principal.kind is PrincipalKind.SHAREPOINT_GROUP and principal.sp_principal_id is not None:
            group_id = principal.sp_principal_id
            return self._cached(("sp", group_id), lambda: self._sharepoint_members(group_id))
        return []

    def _entra_members(self, group_id: str) -> list[Member]:
        members: list[Member] = []
        try:
            for row in self._graph.group_users(group_id):
                if len(members) >= self._max_members:
                    break
                upn = str(row["userPrincipalName"]).lower() if row.get("userPrincipalName") else None
                enabled = row.get("accountEnabled")
                members.append(
                    Member(
                        id=row.get("id"),
                        display_name=str(row.get("displayName") or upn or "Unnamed member"),
                        upn=upn,
                        account_enabled=bool(enabled) if enabled is not None else None,
                        status=_status(bool(enabled) if enabled is not None else None),
                    )
                )
        except UpstreamError as exc:
            return [self._unavailable(f"Entra group members could not be expanded: {exc.message}")]
        return members

    def _sharepoint_members(self, group_id: int) -> list[Member]:
        members: list[Member] = []
        try:
            user_rows = list(self._sharepoint.group_users(group_id))
            parsed_users: list[tuple[dict[str, Any], str]] = []
            for row in user_rows:
                if len(parsed_users) >= self._max_members:
                    break
                login = str(row.get("LoginName") or "")
                match = self._user_pattern.search(login)
                if match and "upn" in match.re.groupindex and match.group("upn"):
                    upn: str | None = match.group("upn").lower()
                else:
                    fallback = row.get("UserPrincipalName") or row.get("Email")
                    upn = str(fallback).lower() if fallback else None
                if upn is not None:
                    parsed_users.append((row, upn))

            # Prefetch accounts in parallel so multiple Graph calls run concurrently
            uncached = [upn for _, upn in parsed_users if ("account", upn) not in self._cache]
            if uncached:
                with ThreadPoolExecutor(max_workers=min(8, len(uncached))) as pool:
                    list(pool.map(self.account, uncached))

            for row, upn in parsed_users:
                account_enabled, status = self.account(upn)
                members.append(
                    Member(
                        id=str(row.get("Id")) if row.get("Id") is not None else None,
                        display_name=str(row.get("Title") or upn),
                        upn=upn,
                        account_enabled=account_enabled,
                        status=status,
                    )
                )
        except UpstreamError as exc:
            return [self._unavailable(f"SharePoint group members could not be expanded: {exc.message}")]
        return members

    @staticmethod
    def _unavailable(message: str) -> Member:
        return Member(id=None, display_name=message, upn=None, account_enabled=None, status=STATUS_UNKNOWN)

    def account(self, upn: str) -> tuple[bool | None, str]:
        """Returns (accountEnabled, status) for one user principal name."""

        def load() -> tuple[bool | None, str]:
            try:
                account = self._graph.user(upn)
            except UpstreamError:
                return None, STATUS_UNKNOWN
            except Exception:
                return None, STATUS_UNKNOWN
            if account is None:
                return None, STATUS_MISSING
            enabled = account.get("accountEnabled")
            flag = bool(enabled) if enabled is not None else None
            return flag, _status(flag)

        return self._cached(("account", upn.lower()), load)
