"""Governance documents (list, detail) read from the SharePoint governance columns, enriched with live analytics."""

from __future__ import annotations

from typing import Any

from app.analytics.expiry import ExpiryFinding
from app.analytics.preview import PREVIEW_EXTRACTORS, build_preview
from app.core.config import Settings
from app.core.errors import BadRequestError, NotFoundError
from app.core.governance import Governance, normalize_token
from app.domain.identity import file_extension
from app.domain.snapshot import ItemRecord
from app.services.analytics import AnalyticsService
from app.services.corpus import LibraryCorpus
from app.services.library import LibraryService
from app.services.views import iso, item_view


def label_matches(governance: Governance, group: str, stored: str | None, wanted: str) -> bool:
    if stored is None:
        return False
    target = normalize_token(wanted)
    if normalize_token(stored) == target:
        return True
    key = governance.key_for_label(group, stored)
    return key is not None and normalize_token(key) == target


def category_matches(stored: str | None, wanted: str) -> bool:
    """Knowledge categories have no vocabulary keys, so "Supply Chain" and "supply-chain" both match."""

    return stored is not None and normalize_token(stored) == normalize_token(wanted)


def expiry_view(finding: ExpiryFinding | None) -> dict[str, Any] | None:
    if finding is None:
        return None
    return {
        "expired": finding.expired,
        "expiredBy": list(finding.expired_by),
        "expirationDate": iso(finding.expiration_date),
        "daysPastExpiration": finding.days_past_expiration,
        "reviewDate": iso(finding.review_date),
        "reviewOverdue": finding.review_overdue,
        "overdueBy": list(finding.overdue_by),
        "daysOverdue": finding.days_overdue,
        "textDates": [
            {"kind": entry.kind, "date": entry.value.isoformat(), "snippet": entry.snippet}
            for entry in finding.text_dates
        ],
    }


def document_summary(corpus: LibraryCorpus, item: ItemRecord) -> dict[str, Any]:
    fields = item.fields
    owner = fields.get("knowledgeOwner") or {}
    summary = item_view(corpus, item)
    summary.update({
        "title": fields.get("title") or item.name,
        "size": item.size,
        "artifactId": fields.get("artifactId"),
        "knowledgeCategory": fields.get("knowledgeCategory"),
        "lifecycleStatus": fields.get("lifecycleStatus"),
        "documentIteration": fields.get("documentIteration"),
        "authoritative": fields.get("authoritative"),
        "aiReady": fields.get("aiReady"),
        "reviewDate": iso(fields.get("reviewDate")),
        "expirationDate": iso(fields.get("expirationDate")),
        "effectiveDate": iso(fields.get("effectiveDate")),
        "documentType": fields.get("documentType"),
        "productFamily": fields.get("productFamily"),
        "processArea": fields.get("processArea"),
        "sensitivity": fields.get("sensitivity"),
        "dataQualityStatus": fields.get("dataQualityStatus"),
        "conflictStatus": fields.get("conflictStatus"),
        "trustScore": fields.get("trustScore"),
        "knowledgeOwner": owner.get("upn"),
        "ownerDisplayName": fields.get("ownerDisplayName") or owner.get("displayName"),
        "duplicateOf": fields.get("duplicateOf"),
    })
    return summary


SORT_FIELDS: dict[str, str] = {
    "title": "title",
    "name": "name",
    "modified": "modified",
    "artifactId": "artifactId",
    "lifecycleStatus": "lifecycleStatus",
    "documentIteration": "documentIteration",
    "dataQualityStatus": "dataQualityStatus",
    "trustScore": "trustScore",
    "reviewDate": "reviewDate",
    "expirationDate": "expirationDate",
    "effectiveDate": "effectiveDate",
}


class DocumentService:
    def __init__(
        self,
        *,
        settings: Settings,
        governance: Governance,
        libraries: LibraryService,
        analytics: AnalyticsService,
    ) -> None:
        self._settings = settings
        self._governance = governance
        self._libraries = libraries
        self._analytics = analytics

    def _all(self) -> list[tuple[LibraryCorpus, ItemRecord]]:
        rows: list[tuple[LibraryCorpus, ItemRecord]] = []
        for library in self._libraries.configured():
            corpus = self._libraries.corpus(library.id)
            rows.extend((corpus, item) for item in corpus.snapshot.files)
        return rows

    def list(
        self,
        *,
        lifecycle: str | None,
        iteration: str | None = None,
        data_quality: str | None,
        authoritative: bool | None,
        category: str | None,
        sort: str,
        order: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        if sort not in self._settings.api.api.sortableFields:
            raise BadRequestError(f"sort must be one of {', '.join(self._settings.api.api.sortableFields)}.")
        documents: list[dict[str, Any]] = []
        categories: set[str] = set()
        iterations: set[str] = set()
        for corpus, item in self._all():
            fields = item.fields
            if fields.get("knowledgeCategory"):
                categories.add(str(fields["knowledgeCategory"]))
            if fields.get("documentIteration"):
                iterations.add(str(fields["documentIteration"]))
            if category and not category_matches(fields.get("knowledgeCategory"), category):
                continue
            if iteration and (fields.get("documentIteration") or "").strip().lower() != iteration.strip().lower():
                continue
            if lifecycle and not label_matches(self._governance, "lifecycleStatus", fields.get("lifecycleStatus"),
                                               lifecycle):
                continue
            if data_quality and not label_matches(self._governance, "dataQualityStatus",
                                                  fields.get("dataQualityStatus"), data_quality):
                continue
            if authoritative is not None and bool(fields.get("authoritative")) is not authoritative:
                continue
            documents.append(document_summary(corpus, item))
        field = SORT_FIELDS[sort]
        present = [doc for doc in documents if doc.get(field) not in (None, "")]
        missing = [doc for doc in documents if doc.get(field) in (None, "")]
        present.sort(key=lambda doc: (str(doc[field]).lower() if isinstance(doc[field], str) else doc[field],
                                      doc["id"]), reverse=order == "desc")
        ordered = present + missing
        total = len(ordered)
        start = (page - 1) * page_size
        return {
            "items": ordered[start:start + page_size],
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, -(-total // page_size)),
            "sort": sort,
            "order": order,
            "knowledgeCategories": sorted(categories, key=str.lower),
            "documentIterations": sorted(iterations, key=str.lower),
        }

    def detail(self, item_id: str) -> dict[str, Any]:
        corpus, item = self._libraries.item(item_id)
        if item.kind != "file":
            raise NotFoundError("The identifier does not name a document.")
        fields = item.fields
        summary = document_summary(corpus, item)
        summary.update({
            "businessUnit": fields.get("businessUnit"),
            "sourceSystem": fields.get("sourceSystem"),
            "supersedesDocument": fields.get("supersedesDocument"),
            "trustReasons": fields.get("trustReasons") or [],
            "conflictWith": fields.get("conflictWith") or [],
            "duplicateOf": fields.get("duplicateOf"),
            "contentHash": fields.get("contentHash"),
            "lastValidatedDate": iso(fields.get("lastValidatedDate")),
            "knowledgeOwnerDetail": fields.get("knowledgeOwner"),
            "liveDuplicateRoles": self._analytics.duplicate_roles(corpus).get(item.item_id, []),
            "liveExpiry": expiry_view(self._analytics.expiry(corpus).get(item.item_id)),
        })
        return summary

    def content(self, item_id: str) -> tuple[bytes, str, str]:
        """Returns (bytes, file name, extension) for the in-page viewer. Raises NotFoundError/UpstreamError."""

        corpus, item = self._libraries.item(item_id)
        if item.kind != "file":
            raise NotFoundError("The identifier does not name a document.")
        return corpus.raw_content(item), item.name, file_extension(item.name)

    def preview(self, item_id: str) -> dict[str, Any]:
        """Structured preview (paragraphs/tables, sheets, or slides) for docx, xlsx and pptx files."""

        content, name, extension = self.content(item_id)
        if extension not in PREVIEW_EXTRACTORS:
            raise BadRequestError(f"No structured preview is available for {extension or 'this file type'}.")
        try:
            preview = build_preview(extension, content)
        except Exception as exc:  # office parsers raise many unrelated exception types for damaged files
            raise BadRequestError(f"The document could not be parsed for preview: {exc}") from exc
        preview["name"] = name
        return preview

