"""Evidence handlers. Each answers one intent from the same live services that back the REST endpoints.

Every sentence comes from agent.json (answers, findingIds, draftNotification and limits). The handlers only supply values.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import AgentFindingIds, AgentLimits, AnswerText, DraftNotificationConfig
from app.core.errors import BadRequestError
from app.services.access import AccessService
from app.services.analytics import AnalyticsService
from app.services.documents import document_summary
from app.services.exposure import unique_findings
from app.services.hygiene import HygieneService
from app.services.library import LibraryService
from app.services.membership import STATUS_UNKNOWN
from app.services.notifications import NotificationService

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Exposure finding types are the vocabulary of analytics.exposure.severities (protocol names, not text).
EXPOSURE_TYPES: tuple[str, ...] = ("everyoneIncludingExternal", "everyoneExceptExternal", "anonymousLink",
                                   "organizationLink")


@dataclass
class HandlerContext:
    libraries: LibraryService
    analytics: AnalyticsService
    access: AccessService
    hygiene: HygieneService
    notifications: NotificationService
    exposure_labels: dict[str, str]
    evidence_limit: int
    limits: AgentLimits
    answers: AnswerText
    finding_ids: AgentFindingIds
    draft: DraftNotificationConfig
    prompts: list[dict[str, Any]]
    caller_upn: str | None
    caller_name: str | None
    signed_in_user: str

    def corpora(self) -> list[Any]:
        return [self.libraries.corpus(library.id) for library in self.libraries.configured()]

    def summary(self, item_id: str) -> dict[str, Any]:
        corpus, item = self.libraries.item(item_id)
        return document_summary(corpus, item)

    def citation(self, view: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": view.get("title") or view.get("name"),
            "url": view.get("webUrl"),
            "path": view.get("path"),
            "itemId": view.get("id"),
            "library": view.get("libraryTitle"),
        }


Evidence = dict[str, Any]
Handler = Callable[[HandlerContext, str], Evidence]


def _unique_citations(ctx: HandlerContext, views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    citations: list[dict[str, Any]] = []
    for view in views:
        key = str(view.get("id"))
        if key in seen or not view.get("webUrl"):
            continue
        seen.add(key)
        citations.append(ctx.citation(view))
        if len(citations) >= ctx.evidence_limit:
            break
    return citations


def _user_from_prompt(ctx: HandlerContext, prompt: str) -> str:
    match = EMAIL.search(prompt)
    if match:
        return match.group(0).lower()
    if ctx.caller_upn:
        return ctx.caller_upn.lower()
    raise BadRequestError("Name the user by UPN in the question; the signed-in token carries no UPN.")


def _exposure_findings(ctx: HandlerContext) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for corpus in ctx.corpora():
        findings.extend(ctx.analytics.exposure(corpus))
    return unique_findings(findings)


def _finding_row(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": finding["type"],
        "severity": finding["severity"],
        "principal": finding["principal"],
        "role": finding["role"],
        "grantedVia": finding["grantedVia"],
        "member": finding.get("member"),
        "subject": finding["subject"],
        "detail": finding["detail"],
    }


def handle_exposure(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    selected = [f for f in _exposure_findings(ctx) if f["type"] in EXPOSURE_TYPES]
    counts = Counter(f["type"] for f in selected)
    subjects = {f["subject"]["id"]: f["subject"] for f in selected}
    lines = [answers.exposureSummary.format(count=len(selected), items=len(subjects))]
    for kind in EXPOSURE_TYPES:
        if counts[kind]:
            lines.append(answers.exposureTypeLine.format(label=ctx.exposure_labels.get(kind, kind), count=counts[kind]))
    for finding in selected[: ctx.limits.maxExamples]:
        lines.append(answers.exposureExample.format(
            item=finding["subject"]["name"],
            path=finding["subject"]["path"],
            principal=finding["principal"]["displayName"],
            role=finding["role"],
            severity=finding["severity"],
        ))
    return {
        "lines": lines,
        "facts": {"total": len(selected), "byType": dict(counts)},
        "items": [_finding_row(f) for f in selected[: ctx.evidence_limit]],
        "citations": _unique_citations(ctx, list(subjects.values())),
    }


def handle_user_access(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    upn = _user_from_prompt(ctx, prompt)
    records = ctx.access.records_for(upn)
    distinct_items = {record["item"]["id"] for record in records}
    grant_counts = Counter(record["grantedVia"] for record in records)
    groups = sorted({group for record in records for group in record["via"]})
    grant_text = ", ".join(answers.grantPair.format(kind=kind, count=count)
                           for kind, count in sorted(grant_counts.items())) or answers.grantPathsNone
    lines = [
        answers.userSummary.format(user=upn, items=len(distinct_items), paths=len(records)),
        answers.grantPathsLine.format(paths=grant_text),
    ]
    if groups:
        lines.append(answers.groupsLine.format(groups=", ".join(groups)))
    ordered = sorted(records, key=lambda record: record["item"]["path"].lower())
    return {
        "lines": lines,
        "facts": {"userPrincipalName": upn, "items": len(distinct_items), "paths": len(records),
                  "byGrantedVia": dict(grant_counts), "groups": groups},
        "items": [
            {"title": record["item"]["name"], "path": record["item"]["path"], "role": record["role"],
             "grantedVia": record["grantedVia"], "via": record["via"], "inheritedFrom": record["inheritedFrom"],
             "webUrl": record["item"]["webUrl"], "id": record["item"]["id"]}
            for record in ordered[: ctx.evidence_limit]
        ],
        "citations": _unique_citations(ctx, [record["item"] for record in ordered]),
    }


def handle_broken_inheritance(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    selected = [f for f in _exposure_findings(ctx) if f["type"] == "brokenInheritance"]
    lines = [answers.brokenSummary.format(count=len(selected))]
    for finding in selected[: ctx.limits.maxExamples]:
        grants = ", ".join(answers.grantName.format(principal=g["principal"]["displayName"], role=g["role"])
                           for g in finding["directGrants"])
        lines.append(answers.brokenExample.format(
            item=finding["subject"]["name"], path=finding["subject"]["path"], grants=grants))
    return {
        "lines": lines,
        "facts": {"total": len(selected)},
        "items": [{"subject": f["subject"], "directGrants": f["directGrants"]} for f in selected[: ctx.evidence_limit]],
        "citations": _unique_citations(ctx, [f["subject"] for f in selected]),
    }


def handle_duplicates(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    totals = {"exact": 0, "near": 0, "conflicts": 0}
    for corpus in ctx.corpora():
        result = ctx.analytics.duplicates(corpus)
        totals["exact"] += len(result.exact)
        totals["near"] += len(result.near)
        totals["conflicts"] += len(result.conflicts)
        lines.append(answers.duplicatesLibrary.format(
            library=corpus.library.title,
            exact=len(result.exact),
            near=len(result.near),
            conflicts=len(result.conflicts),
        ))
        for cluster in (*result.exact, *result.near):
            canonical = ctx.summary(cluster.canonical)
            duplicates = [ctx.summary(member) for member in cluster.members if member != cluster.canonical]
            citations.extend([canonical, *duplicates])
            if len(items) < ctx.limits.maxExamples:
                lines.append(answers.duplicateCluster.format(
                    kind=cluster.kind,
                    clusterId=cluster.cluster_id,
                    canonical=canonical["title"],
                    canonicalName=canonical["name"],
                    duplicates=", ".join(d["name"] for d in duplicates),
                ))
            items.append({
                "clusterId": cluster.cluster_id,
                "kind": cluster.kind,
                "canonical": canonical,
                "duplicates": duplicates,
                "similarity": {"min": cluster.similarity_min, "mean": cluster.similarity_mean},
            })
    return {
        "lines": lines,
        "facts": totals,
        "items": items[: ctx.evidence_limit],
        "citations": _unique_citations(ctx, citations),
    }


def handle_expiry(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    expired: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    views: dict[str, dict[str, Any]] = {}
    for corpus in ctx.corpora():
        for item_id, finding in ctx.analytics.expiry(corpus).items():
            if not (finding.expired or finding.review_overdue):
                continue
            view = ctx.summary(item_id)
            views[item_id] = view
            row = {
                **ctx.citation(view),
                "expirationDate": finding.expiration_date.isoformat() if finding.expiration_date else None,
                "reviewDate": finding.review_date.isoformat() if finding.review_date else None,
                "expiredBy": list(finding.expired_by),
                "overdueBy": list(finding.overdue_by),
                "lifecycleStatus": view.get("lifecycleStatus"),
                "knowledgeOwner": view.get("knowledgeOwner"),
            }
            if finding.expired:
                expired.append(row)
            if finding.review_overdue:
                overdue.append(row)
    lines = [answers.expirySummary.format(expired=len(expired), overdue=len(overdue))]
    for row in expired[: ctx.limits.maxExamples]:
        lines.append(answers.expiredExample.format(
            title=row["title"], date=row["expirationDate"], sources=", ".join(row["expiredBy"])))
    for row in overdue[: ctx.limits.maxExamples]:
        lines.append(answers.reviewOverdueExample.format(title=row["title"], date=row["reviewDate"]))
    flagged = [*expired, *overdue]
    unique_ids = list(dict.fromkeys(row["itemId"] for row in flagged))
    return {
        "lines": lines,
        "facts": {"expired": len(expired), "reviewOverdue": len(overdue)},
        "items": [next(row for row in flagged if row["itemId"] == item_id) for item_id in unique_ids][
            : ctx.evidence_limit],
        "citations": _unique_citations(ctx, [views[item_id] for item_id in unique_ids]),
    }


def handle_ownership(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    matches = ctx.hygiene.matches(ctx.finding_ids.missingOwners)
    views = [ctx.summary(match.doc.item.item_id) for match in matches]
    lines = [answers.ownershipSummary.format(count=len(views))]
    lines.extend(answers.ownershipExample.format(title=view["title"], path=view["path"])
                 for view in views[: ctx.limits.maxExamples])
    return {
        "lines": lines,
        "facts": {"missingOwners": len(views)},
        "items": [ctx.citation(view) for view in views[: ctx.evidence_limit]],
        "citations": _unique_citations(ctx, views),
    }


def handle_anomalies(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    rows: list[dict[str, Any]] = []
    for corpus in ctx.corpora():
        rows.extend(ctx.analytics.anomalies(corpus))
    lines = [answers.anomalySummary.format(count=len(rows))]
    for row in rows[: ctx.limits.maxExamples]:
        drivers = ", ".join(c["feature"] for c in row["topContributions"])
        lines.append(answers.anomalyExample.format(
            title=row["title"], score=row["score"], anomaly=row["isAnomaly"], drivers=drivers))
    return {
        "lines": lines,
        "facts": {"candidates": len(rows)},
        "items": rows[: ctx.evidence_limit],
        "citations": _unique_citations(ctx, [row["item"] for row in rows]),
    }


def handle_notifications(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    result = ctx.notifications.create_drafts(
        template_id=ctx.draft.templateId,
        finding_id=ctx.draft.findingId,
        document_ids=None,
        caller_upn=ctx.caller_upn,
    )
    created = result["created"]
    skipped = Counter(entry["reason"] for entry in result["skipped"])
    lines = [answers.notificationsSummary.format(count=len(created), template=ctx.draft.templateId,
                                                 mode=result["mode"])]
    if skipped:
        skipped_text = ", ".join(answers.skippedPair.format(reason=reason, count=count)
                                 for reason, count in sorted(skipped.items()))
        lines.append(answers.notificationsSkipped.format(skipped=skipped_text))
    citations = [ctx.summary(draft["documentId"]) for draft in created]
    return {
        "lines": lines,
        "facts": {"drafted": len(created), "skipped": dict(skipped), "mode": result["mode"]},
        "items": [
            {"id": draft["id"], "status": draft["status"], "to": draft["to"], "subject": draft["subject"],
             "documentId": draft["documentId"]}
            for draft in created[: ctx.evidence_limit]
        ],
        "citations": _unique_citations(ctx, citations),
    }


def handle_backlog(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    summary = ctx.hygiene.summary()
    by_severity: Counter[str] = Counter()
    for finding in summary["findings"]:
        by_severity[finding["severity"]] += finding["count"]
    active = [finding for finding in summary["findings"] if finding["count"]]
    severity_text = ", ".join(answers.severityPair.format(severity=severity, count=count)
                              for severity, count in by_severity.items())
    lines = [answers.backlogSummary.format(severities=severity_text or answers.backlogNone)]
    for finding in active:
        library_text = ", ".join(answers.libraryPair.format(library=name, count=count)
                                 for name, count in finding["byLibrary"].items())
        lines.append(answers.backlogFinding.format(
            title=finding["title"], severity=finding["severity"], count=finding["count"], libraries=library_text))
    return {
        "lines": lines,
        "facts": {"bySeverity": dict(by_severity), "metrics": summary["metrics"],
                  "libraries": summary["libraries"]},
        "items": [{"id": f["id"], "title": f["title"], "severity": f["severity"], "count": f["count"]}
                  for f in summary["findings"]][: ctx.evidence_limit],
        "citations": [],
    }


def handle_orphans(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    selected = [f for f in _exposure_findings(ctx) if f["type"] == "orphanedAccount"]
    lines = [answers.orphanSummary.format(count=len(selected))]
    for finding in selected[: ctx.limits.maxExamples]:
        member = finding.get("member") or {}
        who = member.get("displayName") or finding["principal"]["displayName"]
        lines.append(answers.orphanExample.format(
            item=finding["subject"]["name"],
            path=finding["subject"]["path"],
            who=who,
            status=member.get("status", STATUS_UNKNOWN),
        ))
    return {
        "lines": lines,
        "facts": {"total": len(selected)},
        "items": [_finding_row(f) for f in selected[: ctx.evidence_limit]],
        "citations": _unique_citations(ctx, [f["subject"] for f in selected]),
    }


def handle_conflicts(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    stored = [*ctx.hygiene.matches(ctx.finding_ids.conflictingAuthoritative),
              *ctx.hygiene.matches(ctx.finding_ids.conflictsWithAuthoritative)]
    live: list[dict[str, Any]] = []
    for corpus in ctx.corpora():
        for candidate in ctx.analytics.duplicates(corpus).conflicts:
            live.append({
                "first": ctx.summary(candidate.first),
                "second": ctx.summary(candidate.second),
                "similarity": candidate.similarity,
                "reason": candidate.reason,
            })
    lines = [answers.conflictsSummary.format(stored=len(stored), live=len(live))]
    for candidate in live[: ctx.limits.maxExamples]:
        lines.append(answers.conflictExample.format(
            first=candidate["first"]["title"],
            second=candidate["second"]["title"],
            similarity=candidate["similarity"],
        ))
    views = [ctx.summary(match.doc.item.item_id) for match in stored]
    citations = views + [c for candidate in live for c in (candidate["first"], candidate["second"])]
    stored_rows = [{"title": v["title"], "path": v["path"], "conflictStatus": v["conflictStatus"]} for v in views]
    return {
        "lines": lines,
        "facts": {"stored": len(stored), "liveCandidates": len(live)},
        "items": (stored_rows + live)[: ctx.evidence_limit],
        "citations": _unique_citations(ctx, citations),
    }


def handle_help(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    samples = [str(entry["text"]).replace("{userUpn}", ctx.caller_upn or ctx.signed_in_user)
               for entry in ctx.prompts]
    lines = [answers.helpIntro]
    lines.extend(answers.helpExample.format(example=sample) for sample in samples[: ctx.limits.maxExamples])
    return {"lines": lines, "facts": {"examples": len(samples)}, "items": [], "citations": []}


HANDLERS: dict[str, Handler] = {
    "exposure": handle_exposure,
    "userAccess": handle_user_access,
    "brokenInheritance": handle_broken_inheritance,
    "duplicates": handle_duplicates,
    "expiry": handle_expiry,
    "ownership": handle_ownership,
    "anomalies": handle_anomalies,
    "notifications": handle_notifications,
    "backlog": handle_backlog,
    "orphans": handle_orphans,
    "conflicts": handle_conflicts,
    "help": handle_help,
}
