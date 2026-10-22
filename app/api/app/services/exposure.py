"""Over-exposure findings derived from grants: claims, sharing links, guests, broken inheritance and orphaned accounts.

Inherited grants are reported once at their source (the library, the site, or the ancestor folder) rather than on
every descendant. Severities come from analytics.exposure.severities and finding text from analytics.exposure.details.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.core.config import ExposureDetails, Settings
from app.domain.permissions import PermissionEntry
from app.domain.principals import CLAIM_SCOPE_INCLUDING_EXTERNAL, PrincipalKind
from app.services.corpus import LibraryCorpus
from app.services.membership import STATUS_DISABLED, STATUS_MISSING, STATUS_UNKNOWN, Member, MembershipService
from app.services.views import item_view, library_view, site_view

ORPHAN_STATUSES = frozenset({STATUS_DISABLED, STATUS_MISSING})


def unique_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Site-level grants are evaluated once per library corpus, so the same finding can arrive more than once."""

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for finding in findings:
        if finding["id"] not in seen:
            seen.add(finding["id"])
            unique.append(finding)
    return unique


class ExposureService:
    def __init__(self, *, settings: Settings, membership: MembershipService) -> None:
        self._settings = settings
        self._membership = membership
        exposure = settings.analytics.exposure
        self._details: ExposureDetails = exposure.details
        self._external = re.compile(exposure.externalUserPattern, re.IGNORECASE)
        self._anonymous = frozenset(exposure.anonymousLinkScopes)
        self._organization = frozenset(exposure.organizationLinkScopes)
        self._severities = dict(exposure.severities)
        self._order = {name: rank for rank, name in enumerate(exposure.severityOrder)}

    def severity(self, finding_type: str) -> str:
        return self._severities[finding_type]

    def findings(self, corpus: LibraryCorpus) -> list[dict[str, Any]]:
        return corpus.memo("exposure-findings", lambda: self._compute(corpus))

    def sort_key(self, finding: dict[str, Any]) -> tuple[int, str, str]:
        return (self._order.get(finding["severity"], len(self._order)), finding["subject"]["path"], finding["id"])

    def _compute(self, corpus: LibraryCorpus) -> list[dict[str, Any]]:
        origin = corpus.web_url("").rstrip("/")
        findings: list[dict[str, Any]] = []
        containers = corpus.snapshot.container_entries()
        library_subject = library_view(corpus, origin)
        for entry in containers.get("library", []):
            findings.extend(self._entry_findings(library_subject, entry))
        site_subject = site_view(
            name=self._settings.site.server_relative_path,
            path=self._settings.site.server_relative_path,
            origin=origin,
            unique=True,
        )
        for entry in containers.get("site", []):
            findings.extend(self._entry_findings(site_subject, entry))

        items = corpus.snapshot.items
        corpus.prefetch_links(items)
        for item in items:
            subject = item_view(corpus, item)
            own = [entry for entry in corpus.snapshot.entries_for(item) + corpus.links(item) if not entry.inherited]
            direct_users = [entry for entry in own if entry.principal.kind is PrincipalKind.USER]
            if item.unique and direct_users:
                findings.append(self._broken_inheritance(subject, direct_users))
            for entry in own:
                findings.extend(self._entry_findings(subject, entry))
        findings.sort(key=self.sort_key)
        return findings

    def _finding(
        self,
        finding_type: str,
        subject: dict[str, Any],
        entry: PermissionEntry,
        *,
        detail: str,
        member: Member | None = None,
    ) -> dict[str, Any]:
        suffix = f":{member.upn}" if member and member.upn else ""
        return {
            "id": f"{finding_type}:{subject['id']}:{entry.principal.key}{suffix}",
            "type": finding_type,
            "severity": self.severity(finding_type),
            "subject": subject,
            "principal": entry.principal.to_json(),
            "role": entry.role,
            "grantedVia": entry.granted_via,
            "member": member.to_json() if member else None,
            "detail": detail,
        }

    def _entry_findings(self, subject: dict[str, Any], entry: PermissionEntry) -> list[dict[str, Any]]:
        principal = entry.principal
        details = self._details
        findings: list[dict[str, Any]] = []
        if principal.kind is PrincipalKind.CLAIMS:
            finding_type = (
                "everyoneIncludingExternal"
                if principal.claim_scope == CLAIM_SCOPE_INCLUDING_EXTERNAL
                else "everyoneExceptExternal"
            )
            findings.append(self._finding(finding_type, subject, entry,
                                          detail=details.everyoneHolds.format(principal=principal.display_name,
                                                                              role=entry.role)))
        elif principal.kind is PrincipalKind.SHARING_LINK:
            scope = entry.link_scope or "users"
            if scope in self._anonymous:
                finding_type = "anonymousLink"
            elif scope in self._organization:
                finding_type = "organizationLink"
            else:
                finding_type = "specificPeopleLink"
            findings.append(self._finding(finding_type, subject, entry,
                                          detail=details.linkAccess.format(principal=principal.display_name,
                                                                           role=entry.role)))
        elif principal.kind is PrincipalKind.USER:
            if principal.upn and self._external.search(principal.upn):
                findings.append(self._finding("externalUserDirectGrant", subject, entry,
                                              detail=details.externalGuest.format(upn=principal.upn,
                                                                                  role=entry.role)))
            if principal.upn:
                enabled, status = self._membership.account(principal.upn)
                if status in ORPHAN_STATUSES:
                    member = Member(None, principal.display_name, principal.upn, enabled, status)
                    findings.append(self._finding("orphanedAccount", subject, entry,
                                                  detail=self._orphan_detail(status), member=member))
        elif principal.is_group:
            for member in self._membership.members(principal):
                if member.status in ORPHAN_STATUSES:
                    findings.append(self._finding("orphanedAccount", subject, entry,
                                                  detail=self._orphan_detail(member.status), member=member))
        return findings

    def _orphan_detail(self, status: str) -> str:
        if status == STATUS_MISSING:
            return self._details.orphanMissing
        if status == STATUS_UNKNOWN:
            return self._details.orphanUnknown
        return self._details.orphanDisabled

    def _broken_inheritance(self, subject: dict[str, Any], direct_users: list[PermissionEntry]) -> dict[str, Any]:
        return {
            "id": f"brokenInheritance:{subject['id']}",
            "type": "brokenInheritance",
            "severity": self.severity("brokenInheritance"),
            "subject": subject,
            "principal": None,
            "role": None,
            "grantedVia": "direct",
            "member": None,
            "directGrants": [
                {"principal": entry.principal.to_json(), "role": entry.role} for entry in direct_users
            ],
            "detail": self._details.brokenInheritance.format(count=len(direct_users)),
        }
