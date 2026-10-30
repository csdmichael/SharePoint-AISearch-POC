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
from app.domain.identity import file_extension
from app.services.access import AccessService
from app.services.analytics import AnalyticsService
from app.services.documents import document_summary
from app.services.exposure import unique_findings
from app.services.hygiene import HygieneService
from app.services.library import LibraryService
from app.services.membership import STATUS_UNKNOWN
from app.services.notifications import NotificationService
from app.services.sites import SiteService

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MEETING_NUMBER = re.compile(r"\bmeeting[\s_-]*(\d{1,3})\b", re.IGNORECASE)
WEBVTT_TIMESTAMP = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")
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
    sites: SiteService
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


def _meeting_number_from_prompt(prompt: str) -> int | None:
    match = MEETING_NUMBER.search(prompt)
    if match is None:
        return None
    return int(match.group(1))


def _meeting_matcher(meeting_number: int | None) -> Callable[[str], bool]:
    if meeting_number is None:
        return lambda text: "meeting" in text
    pattern = re.compile(rf"\bmeeting[\s_-]*0*{meeting_number}\b")
    return lambda text: bool(pattern.search(text))


def _draft_or_incomplete(view: dict[str, Any]) -> bool:
    title = str(view.get("title") or "").lower()
    path = str(view.get("path") or "").lower()
    lifecycle = str(view.get("lifecycleStatus") or "").lower()
    iteration = str(view.get("documentIteration") or "").lower()
    return any(flag in f"{title} {path} {lifecycle} {iteration}" for flag in ("draft", "incomplete", "wip"))


def _transcript_excerpt(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or WEBVTT_TIMESTAMP.match(line) or line.isdigit():
            continue
        if line.startswith("NOTE "):
            continue
        lines.append(line)
        if len(lines) >= 4:
            break
    excerpt = " ".join(lines)
    return excerpt[:600] + ("..." if len(excerpt) > 600 else "")


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


def _member_text(members: list[dict[str, Any]], limit: int = 8) -> str:
    names = [str(m.get("displayName") or m.get("userPrincipalName") or m.get("upn") or "") for m in members]
    names = [name for name in names if name]
    if not names:
        return "n/a"
    extra = f" and {len(names) - limit} more" if len(names) > limit else ""
    return ", ".join(names[:limit]) + extra


def _libraries_named(ctx: HandlerContext, prompt: str) -> list[Any]:
    libraries = ctx.libraries.configured()
    text = prompt.lower()
    meeting_words = ("meeting", "recording", "transcript", "video")
    named = [lib for lib in libraries if lib.title.lower() in text]
    if not named:
        wants_meetings = any(word in text for word in meeting_words)
        named = [lib for lib in libraries if (any(w in lib.title.lower() for w in meeting_words)) == wants_meetings]
    return named or libraries


def handle_library_access(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    lines: list[str] = []
    rows: list[dict[str, Any]] = []
    totals = Counter()
    for library in _libraries_named(ctx, prompt):
        payload = ctx.sites.permissions(library.id)
        entries = payload["entries"]
        links = [e for e in entries if e["principal"]["type"] == "sharingLink"]
        inheritance = ("This library has unique permissions." if payload["inheritance"]["hasUniquePermissions"]
                       else "This library inherits permissions from the site.")
        if not entries:
            lines.append(answers.libraryAccessNone.format(library=library.title))
            continue
        lines.append(answers.libraryAccessSummary.format(
            library=library.title, principals=len(entries) - len(links), links=len(links), inheritance=inheritance))
        for entry in entries:
            principal = entry["principal"]
            members = entry.get("expandedMembers") or []
            kind = principal["type"]
            if kind == "sharingLink":
                kind = f"{entry.get('linkScope') or 'sharing'} link"
            totals[entry["grantedVia"]] += 1
            if len(rows) < ctx.limits.maxExamples:
                lines.append(answers.libraryAccessLine.format(
                    principal=principal["displayName"], kind=kind, role=entry["role"],
                    grantedVia=entry["grantedVia"], members=_member_text(members)))
            rows.append({
                "library": library.title,
                "principal": principal["displayName"],
                "type": kind,
                "role": entry["role"],
                "grantedVia": entry["grantedVia"],
                "memberCount": len(members),
                "members": _member_text(members),
                "linkScope": entry.get("linkScope"),
                "inherited": entry["inheritedFrom"] is not None,
            })
    return {
        "lines": lines or [answers.libraryAccessNone.format(library="the requested library")],
        "facts": {"principals": len(rows), "byGrantedVia": dict(totals)},
        "items": rows[: ctx.evidence_limit],
        "citations": [],
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


def handle_meeting_transcripts(ctx: HandlerContext, prompt: str) -> Evidence:
    answers = ctx.answers
    meeting_number = _meeting_number_from_prompt(prompt)
    matches_meeting = _meeting_matcher(meeting_number)
    transcript_views: list[dict[str, Any]] = []
    transcript_rows: list[tuple[Any, Any, dict[str, Any]]] = []
    recording_views: list[dict[str, Any]] = []
    skipped_drafts = 0

    for corpus in ctx.corpora():
        for item in corpus.snapshot.files:
            ext = file_extension(item.name)
            if ext not in {".vtt", ".txt", ".mp4"}:
                continue
            view = ctx.summary(item.item_id)
            haystack = f"{item.name} {view.get('title', '')} {view.get('path', '')}".lower()
            if not matches_meeting(haystack):
                continue
            if _draft_or_incomplete(view):
                skipped_drafts += 1
                continue
            if ext in {".vtt", ".txt"}:
                transcript_views.append(view)
                transcript_rows.append((corpus, item, view))
            else:
                recording_views.append(view)

    meeting_label = f"{meeting_number:02d}" if meeting_number is not None else "requested"
    if not transcript_rows:
        lines = [
            answers.meetingDraftExcluded.format(meeting=meeting_label)
            if skipped_drafts > 0
            else answers.meetingNotFound.format(meeting=meeting_label)
        ]
        return {
            "lines": lines,
            "facts": {"meeting": meeting_number, "transcripts": 0, "recordings": len(recording_views),
                      "draftsExcluded": skipped_drafts},
            "items": [],
            "citations": [],
        }

    transcript_rows.sort(key=lambda row: (file_extension(row[1].name) != ".vtt", str(row[2].get("path") or "")))
    transcript_corpus, transcript_item, transcript_view = transcript_rows[0]
    transcript_text = transcript_corpus.text(transcript_item).text or ""
    excerpt = _transcript_excerpt(transcript_text)
    transcript_stem = transcript_item.name.rsplit(".", 1)[0].lower()
    recording = next((view for view in recording_views if str(view.get("name", "")).lower().startswith(transcript_stem)), None)
    if recording is None and recording_views:
        recording = recording_views[0]
    recording_name = str(recording.get("title") or recording.get("name")) if recording else "no matching recording found"
    lines = [
        answers.meetingSummary.format(
            meeting=meeting_label,
            transcript=transcript_view.get("title") or transcript_view.get("name"),
            recording=recording_name,
        )
    ]
    if excerpt:
        lines.append(answers.meetingExcerpt.format(excerpt=excerpt))
    citations_source = [transcript_view] + ([recording] if recording is not None else [])
    return {
        "lines": lines,
        "facts": {"meeting": meeting_number, "transcripts": len(transcript_rows), "recordings": len(recording_views),
                  "draftsExcluded": skipped_drafts},
        "items": [ctx.citation(view) for view in citations_source][: ctx.evidence_limit],
        "citations": _unique_citations(ctx, citations_source),
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
    "libraryAccess": handle_library_access,
    "brokenInheritance": handle_broken_inheritance,
    "duplicates": handle_duplicates,
    "expiry": handle_expiry,
    "ownership": handle_ownership,
    "anomalies": handle_anomalies,
    "notifications": handle_notifications,
    "backlog": handle_backlog,
    "orphans": handle_orphans,
    "conflicts": handle_conflicts,
    "meetingTranscripts": handle_meeting_transcripts,
    "help": handle_help,
}
