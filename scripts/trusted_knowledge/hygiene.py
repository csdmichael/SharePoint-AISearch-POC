"""Knowledge hygiene: dashboard metrics, finding lists, the JSON payload and the HTML dashboard."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .governance import CONFLICT_AUTHORITATIVE, DATA_QUALITY_GOOD, DRAFT, SUPERSEDED, Assessment, Evaluation
from .policy import HygieneFinding, Policy
from .similarity import EXACT, NEAR

# Presentation details of the artifacts. They are not policy values.
AVERAGE_DIGITS = 1
JSON_INDENT = 2
EVIDENCE_SEPARATOR = "; "


def build_payload(
    evaluation: Evaluation,
    policy: Policy,
    generated_at: datetime,
    document_urls: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "generatedAt": generated_at.isoformat(),
        "asOf": evaluation.as_of.isoformat(),
        "metrics": _metric_values(evaluation, policy),
        "findings": [
            _finding_payload(finding, evaluation, policy, document_urls)
            for finding in policy.hygiene_findings()
        ],
    }


def _metric_values(evaluation: Evaluation, policy: Policy) -> dict[str, Any]:
    assessments = evaluation.assessments
    draft = policy.label("lifecycleStatus", DRAFT)
    superseded = policy.label("lifecycleStatus", SUPERSEDED)
    total = len(assessments)
    computed: dict[str, Any] = {
        "totalIndexedDocuments": total,
        "authoritativeDocuments": _count(assessments, lambda a: a.declared.authoritative),
        "aiReadyDocuments": _count(assessments, lambda a: a.ai_ready),
        "draftDocuments": _count(assessments, lambda a: a.declared.lifecycle_status == draft),
        "supersededDocuments": _count(assessments, lambda a: a.declared.lifecycle_status == superseded),
        "expiredDocuments": _count(assessments, lambda a: a.expired),
        "documentsMissingOwners": _count(assessments, lambda a: not a.owner_present),
        "exactDuplicateCandidates": _count(assessments, lambda a: a.duplicate_kind == EXACT),
        "nearDuplicateCandidates": _count(assessments, lambda a: a.duplicate_kind == NEAR),
        "documentsRequiringReview": _count(assessments, lambda a: a.data_quality != DATA_QUALITY_GOOD),
        "conflictingAuthoritativeDocuments": _count(assessments, lambda a: a.conflict == CONFLICT_AUTHORITATIVE),
        "averageTrustScore": (
            round(sum(a.trust_score for a in assessments) / total, AVERAGE_DIGITS) if total else 0
        ),
    }
    values: dict[str, Any] = {}
    for metric in policy.hygiene_metrics():
        if metric.key not in computed:
            raise ValueError(f"Hygiene metric {metric.key} has no computation.")
        values[metric.key] = computed[metric.key]
    return values


def _count(assessments: Sequence[Assessment], predicate: Callable[[Assessment], bool]) -> int:
    return sum(1 for assessment in assessments if predicate(assessment))


def _finding_payload(
    finding: HygieneFinding,
    evaluation: Evaluation,
    policy: Policy,
    document_urls: Mapping[str, str],
) -> dict[str, Any]:
    documents = sorted(
        (a for a in evaluation.assessments if _matches(finding, a, policy)),
        key=lambda a: a.key,
    )
    return {
        "id": finding.id,
        "title": finding.title,
        "severity": finding.severity,
        "count": len(documents),
        "documents": [_document_payload(a, document_urls, policy) for a in documents],
    }


def _matches(finding: HygieneFinding, assessment: Assessment, policy: Policy) -> bool:
    if finding.rule == "conflictStatus":
        return assessment.conflict == finding.value
    if finding.rule == "duplicateKind":
        return assessment.duplicate_kind == finding.value
    if finding.rule == "expired":
        return assessment.expired
    if finding.rule == "missingOwner":
        return not assessment.owner_present
    if finding.rule == "lifecycleStatus":
        return assessment.declared.lifecycle_status == policy.label("lifecycleStatus", finding.value)
    if finding.rule == "dataQualityNot":
        return assessment.data_quality != finding.value
    raise ValueError(f"Hygiene finding {finding.id} uses unknown rule {finding.rule}.")


def _document_payload(assessment: Assessment, document_urls: Mapping[str, str], policy: Policy) -> dict[str, Any]:
    declared = assessment.declared
    return {
        "fileName": assessment.key,
        "title": declared.title,
        "artifactId": declared.artifact_id,
        "url": document_urls.get(assessment.key),
        "lifecycleStatus": declared.lifecycle_status,
        "dataQualityStatus": policy.label("dataQualityStatus", assessment.data_quality),
        "conflictStatus": policy.label("conflictStatus", assessment.conflict),
        "duplicateOf": assessment.duplicate_of,
        "duplicateKind": (
            policy.label("duplicateKind", assessment.duplicate_kind) if assessment.duplicate_kind else None
        ),
        "conflictWith": list(assessment.conflict_with),
        "trustScore": assessment.trust_score,
        "evidence": list(assessment.evidence),
    }


def render_dashboard_html(payload: Mapping[str, Any], policy: Policy) -> str:
    metric_labels = {metric.key: metric.label for metric in policy.hygiene_metrics()}
    findings = {finding.id: finding for finding in policy.hygiene_findings()}
    lines = [
        "<!doctype html>",
        "<html>",
        f"<head><meta charset=\"utf-8\"><title>{_escape(payload['generatedAt'])}</title></head>",
        "<body>",
        "<dl>",
    ]
    for key, value in payload["metrics"].items():
        lines.append(f"<dt>{_escape(metric_labels[key])}</dt><dd>{_escape(value)}</dd>")
    lines.append("</dl>")
    for entry in payload["findings"]:
        finding = findings[entry["id"]]
        lines.append("<details>")
        lines.append(
            f"<summary>{_escape(finding.title)} ({_escape(finding.severity)}, {_escape(entry['count'])})</summary>"
        )
        lines.append("<ul>")
        lines.extend(f"<li>{_document_html(document)}</li>" for document in entry["documents"])
        lines.append("</ul>")
        lines.append("</details>")
    lines.extend(["</body>", "</html>"])
    return "\n".join(lines)


def _document_html(document: Mapping[str, Any]) -> str:
    name = _escape(document["fileName"])
    link = f'<a href="{_escape(document["url"])}">{name}</a>' if document["url"] else name
    summary = (
        f"{_escape(document['title'])} "
        f"({_escape(document['lifecycleStatus'])}, {_escape(document['dataQualityStatus'])})"
    )
    evidence = ""
    if document["evidence"]:
        evidence = f"<br><small>{_escape(EVIDENCE_SEPARATOR.join(document['evidence']))}</small>"
    return f"{link} {summary}{evidence}"


def json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=JSON_INDENT, ensure_ascii=False) + "\n"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)
