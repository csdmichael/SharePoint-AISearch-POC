"""Permission entries: one principal's role on one item, with how the access was granted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app.domain.principals import Principal, PrincipalClassifier, PrincipalKind

GRANT_DIRECT = "direct"
GRANT_ENTRA_GROUP = "entraGroup"
GRANT_SHAREPOINT_GROUP = "sharePointGroup"
GRANT_INHERITED = "inherited"
GRANT_SHARING_LINK = "sharingLink"
GRANT_EVERYONE = "everyone"
GRANT_VALUES: tuple[str, ...] = (
    GRANT_DIRECT,
    GRANT_ENTRA_GROUP,
    GRANT_SHAREPOINT_GROUP,
    GRANT_INHERITED,
    GRANT_SHARING_LINK,
    GRANT_EVERYONE,
)
LIMITED_ACCESS = "Limited Access"
UNSPECIFIED_ROLE = "Unspecified"

_MECHANISM_BY_KIND: dict[PrincipalKind, str] = {
    PrincipalKind.USER: GRANT_DIRECT,
    PrincipalKind.ENTRA_GROUP: GRANT_ENTRA_GROUP,
    PrincipalKind.SHAREPOINT_GROUP: GRANT_SHAREPOINT_GROUP,
    PrincipalKind.CLAIMS: GRANT_EVERYONE,
    PrincipalKind.SHARING_LINK: GRANT_SHARING_LINK,
    PrincipalKind.OTHER: GRANT_DIRECT,
}


@dataclass(frozen=True)
class SourceRef:
    """The item whose role assignments apply: the item itself, an ancestor, the library or the site."""

    item_id: str
    path: str
    kind: str

    def to_json(self) -> dict[str, str]:
        return {"itemId": self.item_id, "path": self.path, "kind": self.kind}


@dataclass(frozen=True)
class PermissionEntry:
    principal: Principal
    roles: tuple[str, ...]
    granted_via: str
    inherited_from: SourceRef | None = None
    link_scope: str | None = None
    link_type: str | None = None
    grantees: tuple[str, ...] = ()

    @property
    def role(self) -> str:
        return ", ".join(self.roles)

    @property
    def inherited(self) -> bool:
        return self.inherited_from is not None

    def has_role(self, wanted: str) -> bool:
        target = wanted.strip().lower()
        return any(role.lower() == target for role in self.roles)


def role_names(bindings: Iterable[Mapping[str, Any]] | None) -> tuple[str, ...]:
    names = [str(binding.get("Name")) for binding in bindings or [] if binding.get("Name")]
    substantive = tuple(name for name in names if name != LIMITED_ACCESS)
    if substantive:
        return substantive
    if names:
        return (names[0],)
    return (UNSPECIFIED_ROLE,)


def grant_mechanism(kind: PrincipalKind) -> str:
    return _MECHANISM_BY_KIND[kind]


def entries_from_assignments(
    assignments: Iterable[Mapping[str, Any]],
    classifier: PrincipalClassifier,
    *,
    inherited_from: SourceRef | None,
) -> list[PermissionEntry]:
    """Converts raw SharePoint role assignments. Sharing links are skipped here: Graph reports them with scope."""

    entries: list[PermissionEntry] = []
    for assignment in assignments:
        principal = classifier.classify(assignment.get("Member"))
        if principal.kind is PrincipalKind.SHARING_LINK:
            continue
        granted = GRANT_INHERITED if inherited_from is not None else grant_mechanism(principal.kind)
        entries.append(
            PermissionEntry(
                principal=principal,
                roles=role_names(assignment.get("RoleDefinitionBindings")),
                granted_via=granted,
                inherited_from=inherited_from,
            )
        )
    return entries


def entry_json(entry: PermissionEntry) -> dict[str, Any]:
    return {
        "principal": entry.principal.to_json(),
        "role": entry.role,
        "roles": list(entry.roles),
        "grantedVia": entry.granted_via,
        "inheritedFrom": entry.inherited_from.to_json() if entry.inherited_from else None,
        "linkScope": entry.link_scope,
        "linkType": entry.link_type,
    }
