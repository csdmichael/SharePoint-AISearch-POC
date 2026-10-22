"""Live analytics routes: duplicates, expiry, anomalies and over-exposure."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container
from app.auth.validator import require_auditor
from app.container import Container
from app.services.exposure import unique_findings
from app.services.documents import document_summary, expiry_view

router = APIRouter(tags=["analytics"], dependencies=[Depends(require_auditor)])


def _coverage(container: Container, corpora: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "libraryId": corpus.library.id,
            "libraryTitle": corpus.library.title,
            "documentsScanned": len(corpus.snapshot.files),
            "truncated": corpus.snapshot.truncated,
            "warnings": list(corpus.snapshot.warnings),
        }
        for corpus in corpora
    ]


@router.get("/analytics/duplicates", summary="Exact and near-duplicate clusters with canonical copies")
def duplicates(container: Container = Depends(get_container)) -> dict[str, Any]:
    corpora = [container.libraries.corpus(library.id) for library in container.libraries.configured()]
    exact: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    for corpus in corpora:
        result = container.analytics.duplicates(corpus)
        parameters.append({"libraryId": corpus.library.id, **result.parameters})
        for kind, clusters, bucket in (("exact", result.exact, exact), ("near", result.near, near)):
            for cluster in clusters:
                members = []
                for member_id in cluster.members:
                    _, member = container.libraries.item(member_id)
                    summary = document_summary(corpus, member)
                    summary["role"] = "canonical" if member_id == cluster.canonical else "duplicate"
                    summary["duplicateOf"] = None if member_id == cluster.canonical else cluster.canonical
                    members.append(summary)
                bucket.append({
                    "clusterId": cluster.cluster_id,
                    "libraryId": corpus.library.id,
                    "kind": kind,
                    "reason": cluster.reason,
                    "canonical": cluster.canonical,
                    "size": len(cluster.members),
                    "similarity": {"min": cluster.similarity_min, "mean": cluster.similarity_mean},
                    "fingerprint": list(cluster.fingerprint),
                    "members": members,
                })
        for candidate in result.conflicts:
            _, first = container.libraries.item(candidate.first)
            _, second = container.libraries.item(candidate.second)
            conflicts.append({
                "libraryId": corpus.library.id,
                "similarity": candidate.similarity,
                "scope": list(candidate.scope),
                "reason": candidate.reason,
                "first": document_summary(corpus, first),
                "second": document_summary(corpus, second),
            })
    return {
        "exact": exact,
        "near": near,
        "conflictCandidates": conflicts,
        "parameters": parameters,
        "asOfDate": container.analytics.as_of().isoformat(),
        "libraries": _coverage(container, corpora),
    }


@router.get("/analytics/expiry", summary="Expired and review-overdue documents from metadata and text dates")
def expiry(
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    corpora = [container.libraries.corpus(library.id) for library in container.libraries.configured()]
    expired: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for corpus in corpora:
        for item in corpus.snapshot.files:
            finding = container.analytics.expiry(corpus).get(item.item_id)
            if finding is None or not (finding.expired or finding.review_overdue):
                continue
            row = document_summary(corpus, item)
            row["expiry"] = expiry_view(finding)
            if finding.expired:
                expired.append(row)
            if finding.review_overdue:
                overdue.append(row)
    return {
        "asOfDate": container.analytics.as_of().isoformat(),
        "reviewOverdueGraceDays": container.settings.analytics.expiry.reviewOverdueGraceDays,
        "expired": expired,
        "reviewOverdue": overdue,
        "libraries": _coverage(container, corpora),
    }


@router.get("/analytics/anomalies", summary="IsolationForest anomaly scores with per-feature contributions")
def anomalies(container: Container = Depends(get_container)) -> dict[str, Any]:
    corpora = [container.libraries.corpus(library.id) for library in container.libraries.configured()]
    rows: list[dict[str, Any]] = []
    for corpus in corpora:
        rows.extend(container.analytics.anomalies(corpus))
    rows.sort(key=lambda row: (-row["score"], row["item"]["path"]))
    config = container.settings.analytics.anomaly
    return {
        "asOfDate": container.analytics.as_of().isoformat(),
        "features": list(config.features),
        "contamination": config.contamination,
        "topN": config.topN,
        "items": rows,
        "libraries": _coverage(container, corpora),
    }


@router.get("/analytics/exposure", summary="Over-exposure findings from grants, links, guests and orphaned accounts")
def exposure(
    finding_type: str | None = Query(default=None, alias="type", max_length=60),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    corpora = [container.libraries.corpus(library.id) for library in container.libraries.configured()]
    findings: list[dict[str, Any]] = []
    for corpus in corpora:
        findings.extend(container.analytics.exposure(corpus))
    findings = unique_findings(findings)
    if finding_type:
        findings = [finding for finding in findings if finding["type"] == finding_type]
    findings.sort(key=container.exposure.sort_key)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    return {
        "asOfDate": container.analytics.as_of().isoformat(),
        "total": len(findings),
        "bySeverity": counts,
        "findings": findings,
        "libraries": _coverage(container, corpora),
    }
