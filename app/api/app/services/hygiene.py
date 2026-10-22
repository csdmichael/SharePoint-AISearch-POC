"""Hygiene metrics and findings. Definitions (labels, severities, rules, metric keys) come from the shared vocabulary.
Reason text comes from api.config.json (hygiene.reasons) and the sample size from hygiene.sampleSize."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analytics.expiry import ExpiryFinding
from app.core.config import HygieneReasons, Settings
from app.core.errors import NotFoundError
from app.core.governance import Governance
from app.domain.snapshot import ItemRecord
from app.services.analytics import AnalyticsService
from app.services.corpus import LibraryCorpus
from app.services.documents import document_summary, expiry_view, label_matches
from app.services.library import LibraryService


@dataclass
class HygieneDoc:
    corpus: LibraryCorpus
    item: ItemRecord
    view: dict[str, Any]
    expiry: ExpiryFinding | None
    duplicate_roles: list[dict[str, Any]]
    owner_upn: str | None


@dataclass
class FindingMatch:
    doc: HygieneDoc
    reason: str


@dataclass
class HygieneModel:
    as_of: str
    docs: list[HygieneDoc]
    coverage: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    matches: dict[str, list[FindingMatch]] = field(default_factory=dict)
    metrics: list[dict[str, Any]] = field(default_factory=list)


class HygieneService:
    def __init__(
        self,
        *,
        settings: Settings,
        governance: Governance,
        libraries: LibraryService,
        analytics: AnalyticsService,
    ) -> None:
        self._governance = governance
        self._libraries = libraries
        self._analytics = analytics
        self._reasons: HygieneReasons = settings.api.hygiene.reasons
        self._sample_size = settings.api.hygiene.sampleSize

    def _documents(self) -> tuple[list[HygieneDoc], list[dict[str, Any]]]:
        docs: list[HygieneDoc] = []
        coverage: list[dict[str, Any]] = []
        for library in self._libraries.configured():
            corpus = self._libraries.corpus(library.id)
            expiry = self._analytics.expiry(corpus)
            roles = self._analytics.duplicate_roles(corpus)
            files = corpus.snapshot.files
            for item in files:
                owner = item.fields.get("knowledgeOwner") or {}
                docs.append(
                    HygieneDoc(
                        corpus=corpus,
                        item=item,
                        view=document_summary(corpus, item),
                        expiry=expiry.get(item.item_id),
                        duplicate_roles=roles.get(item.item_id, []),
                        owner_upn=owner.get("upn"),
                    )
                )
            coverage.append({
                "libraryId": library.id,
                "libraryTitle": library.title,
                "documentsScanned": len(files),
                "folders": len(corpus.snapshot.folders),
                "truncated": corpus.snapshot.truncated,
                "warnings": list(corpus.snapshot.warnings),
            })
        return docs, coverage

    def _match(self, definition: dict[str, Any], docs: list[HygieneDoc]) -> list[FindingMatch]:
        rule = definition["rule"]
        value = definition.get("value")
        reasons = self._reasons
        matched: list[FindingMatch] = []
        for doc in docs:
            fields = doc.item.fields
            reason: str | None = None
            if rule == "conflictStatus":
                label = self._governance.label("conflictStatus", value)
                if label_matches(self._governance, "conflictStatus", fields.get("conflictStatus"), label):
                    reason = reasons.conflictStatus.format(label=label)
            elif rule == "duplicateKind":
                for role in doc.duplicate_roles:
                    if role["kind"] == value and not role["isCanonical"]:
                        reason = reasons.duplicate.format(
                            kind=self._governance.label("duplicateKind", value), canonical=role["canonical"])
                        break
            elif rule == "expired":
                if doc.expiry is not None and doc.expiry.expired:
                    reason = reasons.expired.format(sources=", ".join(doc.expiry.expired_by))
            elif rule == "missingOwner":
                if doc.owner_upn is None:
                    reason = reasons.missingOwner
            elif rule == "lifecycleStatus":
                label = self._governance.label("lifecycleStatus", value)
                if label_matches(self._governance, "lifecycleStatus", fields.get("lifecycleStatus"), label):
                    reason = reasons.lifecycleStatus.format(label=label)
            elif rule == "dataQualityNot":
                good = self._governance.label("dataQualityStatus", value)
                if not label_matches(self._governance, "dataQualityStatus", fields.get("dataQualityStatus"), good):
                    status = fields.get("dataQualityStatus") or reasons.notRecorded
                    reason = reasons.dataQualityNot.format(status=status)
                elif doc.expiry is not None and doc.expiry.review_overdue:
                    reason = reasons.reviewPassed
            if reason is not None:
                matched.append(FindingMatch(doc=doc, reason=reason))
        return matched

    def _build(self) -> HygieneModel:
        docs, coverage = self._documents()
        matches: dict[str, list[FindingMatch]] = {}
        findings: list[dict[str, Any]] = []
        for definition in self._governance.findings:
            matched = self._match(definition, docs)
            matches[definition["id"]] = matched
            by_library: dict[str, int] = {}
            for match in matched:
                title = match.doc.view["libraryTitle"]
                by_library[title] = by_library.get(title, 0) + 1
            findings.append({
                "id": definition["id"],
                "title": definition["title"],
                "severity": definition["severity"],
                "count": len(matched),
                "byLibrary": by_library,
                "sample": [self._row(match) for match in matched[: self._sample_size]],
            })
        review_ids = {match.doc.item.item_id for match in matches.get("requires-review", [])}
        model = HygieneModel(
            as_of=self._analytics.as_of().isoformat(),
            docs=docs,
            coverage=coverage,
            findings=findings,
            matches=matches,
        )
        model.metrics = self._metrics(docs, review_ids)
        return model

    @staticmethod
    def _row(match: FindingMatch) -> dict[str, Any]:
        return {
            "id": match.doc.item.item_id,
            "title": match.doc.view["title"],
            "name": match.doc.view["name"],
            "libraryTitle": match.doc.view["libraryTitle"],
            "webUrl": match.doc.view["webUrl"],
            "reason": match.reason,
        }

    def _metrics(self, docs: list[HygieneDoc], review_ids: set[str]) -> list[dict[str, Any]]:
        governance = self._governance

        def count(predicate) -> int:
            return sum(1 for doc in docs if predicate(doc))

        def lifecycle_is(doc: HygieneDoc, key: str) -> bool:
            return label_matches(governance, "lifecycleStatus", doc.item.fields.get("lifecycleStatus"),
                                 governance.label("lifecycleStatus", key))

        scores = [doc.item.fields["trustScore"] for doc in docs if doc.item.fields.get("trustScore") is not None]
        values: dict[str, Any] = {
            "totalIndexedDocuments": len(docs),
            "authoritativeDocuments": count(lambda d: bool(d.item.fields.get("authoritative"))),
            "aiReadyDocuments": count(lambda d: bool(d.item.fields.get("aiReady"))),
            "draftDocuments": count(lambda d: lifecycle_is(d, "draft")),
            "supersededDocuments": count(lambda d: lifecycle_is(d, "superseded")),
            "expiredDocuments": count(lambda d: d.expiry is not None and d.expiry.expired),
            "documentsMissingOwners": count(lambda d: d.owner_upn is None),
            "exactDuplicateCandidates": count(
                lambda d: any(r["kind"] == "exact" and not r["isCanonical"] for r in d.duplicate_roles)),
            "nearDuplicateCandidates": count(
                lambda d: any(r["kind"] == "near" and not r["isCanonical"] for r in d.duplicate_roles)),
            "documentsRequiringReview": len(review_ids),
            "conflictingAuthoritativeDocuments": count(
                lambda d: label_matches(governance, "conflictStatus", d.item.fields.get("conflictStatus"),
                                        governance.label("conflictStatus", "conflictingAuthoritative"))),
            "averageTrustScore": round(sum(scores) / len(scores), 1) if scores else None,
        }
        return [
            {"key": metric["key"], "label": metric["label"], "value": values.get(metric["key"])}
            for metric in governance.metrics
        ]

    def summary(self) -> dict[str, Any]:
        model = self._build()
        return {
            "asOfDate": model.as_of,
            "metrics": model.metrics,
            "findings": model.findings,
            "libraries": model.coverage,
        }

    def finding(self, finding_id: str) -> dict[str, Any]:
        model = self._build()
        definition = next((item for item in model.findings if item["id"] == finding_id), None)
        if definition is None:
            raise NotFoundError(f"Hygiene finding '{finding_id}' does not exist.")
        documents = []
        for match in model.matches[finding_id]:
            row = dict(match.doc.view)
            row["reason"] = match.reason
            row["expiry"] = expiry_view(match.doc.expiry)
            row["duplicateRoles"] = match.doc.duplicate_roles
            documents.append(row)
        return {
            "id": definition["id"],
            "title": definition["title"],
            "severity": definition["severity"],
            "count": definition["count"],
            "byLibrary": definition["byLibrary"],
            "asOfDate": model.as_of,
            "documents": documents,
        }

    def matches(self, finding_id: str) -> list[FindingMatch]:
        model = self._build()
        return model.matches.get(finding_id, [])

    def known_finding_ids(self) -> list[str]:
        return [str(item["id"]) for item in self._governance.findings]
