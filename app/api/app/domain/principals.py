"""Principal classification: maps a SharePoint role-assignment member to a typed principal.

Type codes come from config (sharePoint.principalTypes). Login-name patterns come from config
(analytics.loginNamePatterns and analytics.exposure.everyoneLoginPattern) and take precedence over type codes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.core.config import LoginNamePatterns


class PrincipalKind(str, Enum):
    USER = "user"
    ENTRA_GROUP = "entraGroup"
    SHAREPOINT_GROUP = "sharePointGroup"
    CLAIMS = "claims"
    SHARING_LINK = "sharingLink"
    OTHER = "other"


_KIND_BY_NAME = {kind.value: kind for kind in PrincipalKind}
CLAIM_SCOPE_INCLUDING_EXTERNAL = "includingExternal"
CLAIM_SCOPE_EXCEPT_EXTERNAL = "exceptExternal"


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    key: str
    display_name: str
    login_name: str | None = None
    email: str | None = None
    upn: str | None = None
    entra_group_id: str | None = None
    sp_principal_id: int | None = None
    claim_scope: str | None = None

    @property
    def identifier(self) -> str:
        if self.kind is PrincipalKind.USER:
            return self.upn or self.login_name or self.key
        if self.kind is PrincipalKind.ENTRA_GROUP:
            return self.entra_group_id or self.login_name or self.key
        if self.kind is PrincipalKind.SHAREPOINT_GROUP:
            return str(self.sp_principal_id) if self.sp_principal_id is not None else self.key
        if self.kind is PrincipalKind.CLAIMS:
            return self.claim_scope or self.key
        return self.key

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.kind.value,
            "id": self.identifier,
            "displayName": self.display_name,
            "loginName": self.login_name,
            "email": self.email,
        }

    @property
    def is_group(self) -> bool:
        return self.kind in (PrincipalKind.ENTRA_GROUP, PrincipalKind.SHAREPOINT_GROUP)


class PrincipalClassifier:
    def __init__(
        self,
        patterns: LoginNamePatterns,
        *,
        everyone_including_external: str,
        type_map: Mapping[str, str],
        claim_labels: Mapping[str, str],
    ) -> None:
        flags = re.IGNORECASE
        self._user = re.compile(patterns.user, flags)
        self._entra = re.compile(patterns.entraGroup, flags)
        self._sp_group = re.compile(patterns.sharePointGroup, flags)
        self._claim_except = re.compile(patterns.everyoneClaim, flags)
        self._claim_all = re.compile(everyone_including_external, flags)
        self._sharing = re.compile(patterns.sharingLink, flags)
        self._type_map = {str(code): _KIND_BY_NAME[kind] for code, kind in type_map.items()}
        self._claim_labels = dict(claim_labels)

    def classify(self, member: Mapping[str, Any] | None) -> Principal:
        member = member or {}
        login = str(member.get("LoginName") or "")
        title = str(member.get("Title") or "").strip()
        email_raw = member.get("Email")
        email = str(email_raw) if email_raw else None
        sp_id = member.get("Id")
        sp_id_int = int(sp_id) if isinstance(sp_id, int) or (isinstance(sp_id, str) and sp_id.isdigit()) else None
        type_code = "" if member.get("PrincipalType") is None else str(member.get("PrincipalType"))

        if self._claim_except.search(login):
            return self._claim(CLAIM_SCOPE_EXCEPT_EXTERNAL)
        if self._claim_all.search(login):
            return self._claim(CLAIM_SCOPE_INCLUDING_EXTERNAL)
        if self._sharing.search(login):
            return Principal(PrincipalKind.SHARING_LINK, f"link:{login.lower()}", title or login, login_name=login)

        entra_match = self._entra.search(login)
        if entra_match:
            group_id = (entra_match.groupdict().get("id") or "").lower() or None
            return Principal(
                PrincipalKind.ENTRA_GROUP,
                f"entra:{group_id or login.lower()}",
                title or login,
                login_name=login,
                email=email,
                entra_group_id=group_id,
            )
        if self._sp_group.search(login) or self._type_map.get(type_code) is PrincipalKind.SHAREPOINT_GROUP:
            return Principal(
                PrincipalKind.SHAREPOINT_GROUP,
                f"spgroup:{sp_id_int if sp_id_int is not None else (title or login).lower()}",
                title or login,
                login_name=login,
                sp_principal_id=sp_id_int,
            )

        user_match = self._user.search(login)
        if user_match or self._type_map.get(type_code) is PrincipalKind.USER:
            if user_match and "upn" in user_match.re.groupindex and user_match.group("upn"):
                upn = user_match.group("upn").lower()
            else:
                fallback = member.get("UserPrincipalName") or email or login
                upn = str(fallback).lower() if fallback else None
            display = title or upn or login
            resolved_email = email or (upn if upn and "@" in upn and "#ext#" not in upn else None)
            return Principal(
                PrincipalKind.USER,
                f"user:{upn or login.lower()}",
                display,
                login_name=login or None,
                email=resolved_email,
                upn=upn,
                sp_principal_id=sp_id_int,
            )

        mapped = self._type_map.get(type_code, PrincipalKind.OTHER)
        if mapped is PrincipalKind.ENTRA_GROUP:
            return Principal(PrincipalKind.ENTRA_GROUP, f"entra:{login.lower() or title.lower()}",
                             title or login or "Unknown group", login_name=login or None, email=email)
        return Principal(
            PrincipalKind.OTHER,
            f"other:{(login or title).lower()}",
            title or login or "Unknown principal",
            login_name=login or None,
            email=email,
            sp_principal_id=sp_id_int,
        )

    def _claim(self, scope: str) -> Principal:
        return Principal(
            PrincipalKind.CLAIMS,
            f"claims:{scope}",
            self._claim_labels.get(scope, scope),
            login_name=None,
            claim_scope=scope,
        )


def user_key(value: str | None) -> str | None:
    return value.strip().lower() if value and value.strip() else None
