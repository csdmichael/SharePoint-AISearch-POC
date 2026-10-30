"""Orchestrates Save to Knowledge: extract a draft, validate the reviewed draft, publish it, report indexing."""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import ValidationError

from app.agent.service import Caller
from app.core.config import KnowledgeCaptureConfig, SiteSettings
from app.core.errors import ApiError, BadRequestError, NotFoundError, UpstreamError, ValidationFailedError
from app.core.governance import Governance
from app.knowledge.document import ArtifactContent, plain_text, render_docx, render_markdown, safe_file_stem
from app.knowledge.extraction import Extractor
from app.knowledge.governance import GovernanceOutcome, classify, content_hash, evaluate
from app.knowledge.indexing import DemoIndexing, IndexingProvider, SearchIndexing, parse_time
from app.knowledge.models import (
    ARTIFACT_ID_PATTERN,
    CONTENT_FIELDS,
    EMAIL_PATTERN,
    METADATA_FIELDS,
    ORIGIN_AI,
    ORIGIN_DEFAULT,
    ORIGIN_SOURCE,
    ORIGIN_UNKNOWN,
    ExtractRequest,
    ExtractResponse,
    IndexingStatus,
    KnowledgeDraft,
    KnowledgeExtraction,
    Location,
    PublishRequest,
    PublishResult,
)
from app.knowledge.publisher import ArtifactPackage, DemoStore, PublishedDocument, SharePointPublisher

logger = logging.getLogger("sp_acl_api")
GENERATED_CONTENT_FIELDS = frozenset({"title", "executiveSummary"})
MANUAL_PROVIDER = "manual"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


class KnowledgeService:
    def __init__(
        self,
        *,
        config: KnowledgeCaptureConfig,
        governance: Governance,
        site: SiteSettings,
        extractor: Extractor | None,
        publisher: SharePointPublisher,
        indexing: IndexingProvider,
        store: DemoStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config
        self._governance = governance
        self._site = site
        self._extractor = extractor
        self._publisher = publisher
        self._indexing = indexing
        self._store = store
        self._clock = clock
        self._sensitivities = governance.choices(governance.column("sensitivity"))

    @property
    def config(self) -> KnowledgeCaptureConfig:
        return self._config

    @property
    def store(self) -> DemoStore:
        return self._store

    @property
    def sensitivities(self) -> list[str]:
        return list(self._sensitivities)

    @property
    def publishing_demo(self) -> bool:
        return self._publisher.mode == "demo"

    def ensure_enabled(self) -> None:
        if not self._config.enabled:
            raise ApiError("Save to Knowledge is turned off for this deployment.", code="feature_disabled",
                           status_code=404)

    def public_config(self, caller: Caller) -> dict[str, Any]:
        self.ensure_enabled()
        config = self._config
        conversation = config.demo.conversation
        return {
            "enabled": True,
            "caller": {"upn": caller.upn, "name": caller.name},
            "taxonomy": {
                "categories": config.taxonomy.categories,
                "departments": config.taxonomy.departments,
                "sensitivities": self.sensitivities,
            },
            "review": {"defaultMonths": config.extraction.defaultReviewMonths,
                       "maxMonths": config.extraction.maxReviewMonths,
                       "lowConfidenceThreshold": config.extraction.lowConfidenceThreshold},
            "extraction": {
                "provider": self._extractor.provider if self._extractor else None,
                "label": self._extractor.label if self._extractor else None,
                "demo": bool(self._extractor and self._extractor.demo),
                "maxMessages": config.extraction.maxMessages,
                "maxSourceChars": config.extraction.maxSourceChars,
            },
            "publishing": {
                "mode": self._publisher.mode,
                "demo": self.publishing_demo,
                "siteName": self._site.display_name,
                "libraryName": config.publish.libraryName,
                "folder": config.publish.folder,
                "sourceType": config.publish.sourceType,
            },
            "indexing": {"mode": self._indexing.mode, "scheduleHint": config.indexing.scheduleHint},
            "demo": {
                "query": config.demo.query,
                "conversation": conversation.model_dump(),
            },
        }

    def extract(self, request: ExtractRequest, caller: Caller) -> ExtractResponse:
        self.ensure_enabled()
        limits = self._config.extraction
        if len(request.messages) > limits.maxMessages:
            raise BadRequestError(f"Select at most {limits.maxMessages} messages.")
        if sum(len(message.text) for message in request.messages) > limits.maxSourceChars:
            raise BadRequestError("The selected messages are too long. Select fewer or shorter messages.")
        if self._extractor is None:
            raise UpstreamError(
                "Microsoft Foundry",
                "AI extraction is not configured. Set the Foundry project and the extraction model deployment "
                "(see Save to Knowledge Demo in the README), or fill in the draft manually.",
                code="extraction_unavailable", status_code=503,
            )
        try:
            extraction = self._extractor.extract(
                request.messages, conversation_id=request.conversationId, source_description=request.sourceDescription
            )
        except ApiError:
            raise
        except (ValidationError, ValueError) as exc:
            logger.warning("Knowledge extraction returned unusable output: %s", type(exc).__name__)
            raise UpstreamError("Microsoft Foundry", "the extraction result was not usable. Try again or fill in the draft manually.",
                                code="extraction_invalid") from None
        except Exception:
            logger.exception("Knowledge extraction failed unexpectedly")
            raise UpstreamError("Microsoft Foundry", "knowledge extraction failed unexpectedly. Try again or fill in the draft manually.",
                                code="extraction_failed") from None
        draft, warnings = self._build_draft(extraction, caller, request)
        return ExtractResponse(
            draft=draft, provider=self._extractor.provider, providerLabel=self._extractor.label,
            demo=self._extractor.demo, messageCount=len(request.messages), warnings=warnings,
        )

    def blank_draft(self, caller: Caller) -> KnowledgeDraft:
        today = self._clock().date()
        return KnowledgeDraft(
            ownerName=caller.name or "", ownerUpn=caller.upn or "", sourceType=self._config.publish.sourceType,
            sensitivity=self._sensitivities[0] if self._sensitivities else "",
            category=self._config.taxonomy.fallbackCategory,
            reviewDate=add_months(today, self._config.extraction.defaultReviewMonths).isoformat(),
        )

    def _build_draft(
        self, extraction: KnowledgeExtraction, caller: Caller, request: ExtractRequest
    ) -> tuple[KnowledgeDraft, list[str]]:
        config = self._config
        today = self._clock().date()
        warnings: list[str] = []
        claimed = {item.field: item.origin for item in extraction.fieldOrigins}

        category = extraction.category
        if category not in config.taxonomy.categories:
            warnings.append(f"The model suggested the category '{category}', which is not allowed. Set to {config.taxonomy.fallbackCategory}.")
            category = config.taxonomy.fallbackCategory
        sensitivity = extraction.sensitivity
        if sensitivity not in self._sensitivities:
            restrictive = self._sensitivities[1] if len(self._sensitivities) > 1 else sensitivity
            warnings.append(f"The suggested sensitivity '{sensitivity}' is not valid. Set to {restrictive}; review it.")
            sensitivity = restrictive

        review = self._default_review_date(today)
        review_origin = ORIGIN_DEFAULT
        if extraction.suggestedReviewDate:
            suggested = date.fromisoformat(extraction.suggestedReviewDate)
            if today < suggested <= add_months(today, config.extraction.maxReviewMonths):
                review, review_origin = suggested, ORIGIN_AI
            else:
                warnings.append("The suggested review date was outside the allowed window. A default was used.")

        facts = list(dict.fromkeys(fact.strip() for fact in extraction.keyFacts if fact.strip()))
        source_description = (
            extraction.sourceDescription or request.sourceDescription
            or f"Teams collaboration, {len(request.messages)} selected message(s)"
        )
        draft = KnowledgeDraft(
            title=extraction.title,
            executiveSummary=extraction.executiveSummary,
            category=category,
            issueContext=extraction.issueContext or "",
            rootCause=extraction.rootCause or "",
            decision=extraction.decision or "",
            recommendedAction=extraction.recommendedAction or "",
            keyFacts=facts,
            department=extraction.department or "",
            product=extraction.product or "",
            ownerName=caller.name or "",
            ownerUpn=caller.upn or "",
            ownerMention=extraction.owner or "",
            sourceType=config.publish.sourceType,
            sourceDescription=source_description,
            sensitivity=sensitivity,
            reviewDate=review.isoformat(),
            tags=list(dict.fromkeys(tag.strip() for tag in extraction.tags if tag.strip())),
            confidence=round(extraction.confidence, 2),
        )
        values = draft.model_dump()
        origins: dict[str, str] = {}
        for name in CONTENT_FIELDS:
            default = ORIGIN_AI if name in GENERATED_CONTENT_FIELDS else ORIGIN_SOURCE
            origins[name] = claimed.get(name, default) if values.get(name) else ORIGIN_UNKNOWN
        origins["sourceDescription"] = ORIGIN_SOURCE
        for name in METADATA_FIELDS:
            origins[name] = ORIGIN_UNKNOWN if not values.get(name) else claimed.get(name, ORIGIN_AI)
        origins["reviewDate"] = review_origin
        origins["owner"] = ORIGIN_DEFAULT if draft.ownerUpn else ORIGIN_UNKNOWN
        draft.origins = origins  # type: ignore[assignment]
        if extraction.confidence < config.extraction.lowConfidenceThreshold:
            warnings.append("Low confidence: the selected messages may not contain enough durable knowledge. Review every field.")
        if not draft.ownerUpn:
            warnings.append("Your sign-in did not provide an email address. Enter the knowledge owner's email.")
        return draft, warnings

    def _default_review_date(self, today: date) -> date:
        return add_months(today, self._config.extraction.defaultReviewMonths)

    def validate(self, request: PublishRequest) -> list[str]:
        today = self._clock().date()
        limits = self._config.extraction
        problems: list[str] = []
        if not request.attested:
            problems.append("Confirm that you reviewed the content and accept ownership before publishing.")
        if len(request.title.strip()) < 5:
            problems.append("Title must have at least 5 characters.")
        if request.category not in self._config.taxonomy.categories:
            problems.append(f"Category must be one of: {', '.join(self._config.taxonomy.categories)}.")
        if request.sensitivity not in self._sensitivities:
            problems.append(f"Sensitivity must be one of: {', '.join(self._sensitivities)}.")
        try:
            review = date.fromisoformat(request.reviewDate)
            if review <= today:
                problems.append("Review date must be in the future.")
            elif review > add_months(today, limits.maxReviewMonths):
                problems.append(f"Review date must be within {limits.maxReviewMonths} months.")
        except ValueError:
            problems.append("Review date must be a valid date (YYYY-MM-DD).")
        if not EMAIL_PATTERN.match(request.ownerUpn):
            problems.append("Knowledge owner must be an email address (user principal name).")
        if not (request.decision.strip() or request.recommendedAction.strip() or request.rootCause.strip()):
            problems.append("Add a decision, a root cause or a recommended action; durable knowledge needs at least one.")
        return problems

    def publish(self, request: PublishRequest, caller: Caller) -> PublishResult:
        self.ensure_enabled()
        problems = self.validate(request)
        if problems:
            raise ValidationFailedError(" ".join(problems), code="invalid_metadata")
        config = self._config
        now = self._clock()
        today = now.date()
        review = date.fromisoformat(request.reviewDate)
        artifact_id = f"{config.publish.artifactIdPrefix}-{uuid.uuid4().hex[:8].upper()}"
        outcome = evaluate(
            self._governance, authoritative=request.authoritative, owner_present=True, review_date=review,
            sensitivity=request.sensitivity, source_system=config.publish.sourceSystem, today=today,
        )
        content = self._content(request, artifact_id, outcome, now, caller)
        fields = self._fields(request, artifact_id, outcome, content, today, review)
        package = ArtifactPackage(
            artifact_id=artifact_id,
            file_name=f"{safe_file_stem(request.title)}.docx",
            docx=render_docx(content, author=request.ownerName or request.ownerUpn),
            markdown=render_markdown(content),
            fields=fields,
            owner_upn=request.ownerUpn,
            metadata={
                "artifactId": artifact_id, "title": request.title, "publishedAt": now.isoformat(),
                "aiReady": outcome.ai_ready, "category": request.category, "tags": request.tags,
                "summary": request.executiveSummary, "context": request.issueContext, "rootCause": request.rootCause,
                "decision": request.decision, "recommendedAction": request.recommendedAction,
                "keyFacts": request.keyFacts, "publishedBy": caller.upn,
            },
        )
        published = self._publisher.publish(package)
        indexing = self._indexing.status(artifact_id, published_at=now, ai_ready=outcome.ai_ready)
        return self._result(request, artifact_id, outcome, published, now, indexing)

    def _content(
        self, request: PublishRequest, artifact_id: str, outcome: GovernanceOutcome, now: datetime, caller: Caller
    ) -> ArtifactContent:
        method = (
            "Entered manually in Save to Knowledge"
            if request.extractionProvider == MANUAL_PROVIDER
            else f"AI-assisted extraction ({request.extractionProvider}), reviewed and edited by the knowledge owner"
        )
        owner = f"{request.ownerName} ({request.ownerUpn})" if request.ownerName else request.ownerUpn
        rows = (
            ("Artifact ID", artifact_id),
            ("Content category", request.category),
            ("Department", request.department or "Not specified"),
            ("Product / project", request.product or "Not specified"),
            ("Knowledge owner", owner),
            ("Lifecycle status", outcome.lifecycle_status),
            ("Authoritative", "Yes" if request.authoritative else "No"),
            ("Sensitivity", request.sensitivity),
            ("Published", now.date().isoformat()),
            ("Review date", request.reviewDate),
            ("AI ready", "Yes" if outcome.ai_ready else "No"),
            ("Trust score", f"{outcome.trust_score}/100"),
            ("Source type", request.sourceType or self._config.publish.sourceType),
            ("Tags", ", ".join(request.tags) or "None"),
            ("Retention", "Only the summarized knowledge is kept. The source conversation is not stored."),
        )
        return ArtifactContent(
            artifact_id=artifact_id, title=request.title, summary=request.executiveSummary, context=request.issueContext,
            root_cause=request.rootCause, decision=request.decision, recommended_action=request.recommendedAction,
            key_facts=tuple(request.keyFacts), source_type=request.sourceType or self._config.publish.sourceType,
            source_description=request.sourceDescription, extraction_method=method, governance=rows,
        )

    def _fields(
        self, request: PublishRequest, artifact_id: str, outcome: GovernanceOutcome, content: ArtifactContent,
        today: date, review: date,
    ) -> dict[str, Any]:
        gov, publish = self._governance, self._config.publish
        column = gov.column

        def day(value: date) -> str:
            return f"{value.isoformat()}T00:00:00Z"

        process_area = classify(gov, "processArea", f"{request.title} {request.executiveSummary} {request.category}")
        product_family = next(
            (choice for choice in gov.choices(column("productFamily")) if request.product and choice.lower() in request.product.lower()),
            None,
        )
        source_type = request.sourceType or publish.sourceType
        lineage = f"{source_type}: {request.sourceDescription or 'selected messages'}"[:255]
        fields: dict[str, Any] = {
            column("title"): request.title,
            column("artifactId"): artifact_id,
            column("knowledgeCategory"): publish.departmentToKnowledgeCategory.get(request.department, publish.defaultKnowledgeCategory),
            column("sourceTable"): lineage,
            column("sourceSystem"): publish.sourceSystem,
            column("ownerDisplayName"): request.ownerName or request.ownerUpn,
            column("lifecycleStatus"): outcome.lifecycle_status,
            column("documentIteration"): publish.documentIteration,
            column("authoritative"): request.authoritative,
            column("reviewDate"): day(review),
            column("documentType"): publish.categoryToDocumentType[request.category],
            column("sensitivity"): request.sensitivity,
            column("effectiveDate"): day(today),
            column("businessUnit"): request.department[:255],
            column("aiReady"): outcome.ai_ready,
            column("trustScore"): outcome.trust_score,
            column("dataQualityStatus"): outcome.data_quality,
            column("conflictStatus"): outcome.conflict_status,
            column("conflictWith"): "",
            column("duplicateOf"): "",
            column("contentHash"): content_hash(gov, plain_text(content)),
            column("trustReasons"): "\n".join(outcome.trust_reasons)[:2000],
            column("lastValidatedDate"): day(today),
        }
        if process_area in gov.choices(column("processArea")):
            fields[column("processArea")] = process_area
        if product_family:
            fields[column("productFamily")] = product_family
        return fields

    def _result(
        self, request: PublishRequest, artifact_id: str, outcome: GovernanceOutcome, published: PublishedDocument,
        now: datetime, indexing: IndexingStatus,
    ) -> PublishResult:
        applied = {name: value if isinstance(value, (str, int, bool)) else str(value)
                   for name, value in published.applied_fields.items()}
        return PublishResult(
            artifactId=artifact_id, title=request.title, fileName=published.file_name, category=request.category,
            ownerName=request.ownerName or request.ownerUpn, ownerUpn=request.ownerUpn,
            publishedAt=now.astimezone(timezone.utc).replace(microsecond=0).isoformat(), reviewDate=request.reviewDate,
            lifecycleStatus=outcome.lifecycle_status, authoritative=request.authoritative, aiReady=outcome.ai_ready,
            aiReadyBlockers=list(outcome.blockers), trustScore=outcome.trust_score,
            location=Location(mode="demo" if published.mode == "demo" else "graph", siteName=published.site_name,
                              libraryName=published.library_name, folder=published.folder, webUrl=published.web_url),
            demo=published.mode == "demo", appliedFields=applied, skippedFields=published.skipped_fields,
            warnings=published.warnings, indexing=indexing,
        )

    def _published_info(self, artifact_id: str, published_at: str | None, ai_ready: bool | None) -> tuple[datetime, bool]:
        if not ARTIFACT_ID_PATTERN.match(artifact_id):
            raise BadRequestError("artifactId is not valid.")
        if self._publisher.mode == "demo":
            record = self._store.metadata(artifact_id)
            when = parse_time(record.get("publishedAt"))
            if when is None:
                raise NotFoundError("The knowledge artifact was not found.")
            return when, bool(record.get("aiReady"))
        when = parse_time(published_at)
        if when is None or when > self._clock() + timedelta(minutes=5):
            raise BadRequestError("publishedAt must be the ISO timestamp returned when the artifact was published.")
        return when, True if ai_ready is None else ai_ready

    def indexing_status(self, artifact_id: str, published_at: str | None, ai_ready: bool | None) -> IndexingStatus:
        self.ensure_enabled()
        when, ready = self._published_info(artifact_id, published_at, ai_ready)
        return self._indexing.status(artifact_id, published_at=when, ai_ready=ready)

    def trigger_indexing(self, artifact_id: str, published_at: str | None, ai_ready: bool | None) -> IndexingStatus:
        self.ensure_enabled()
        when, ready = self._published_info(artifact_id, published_at, ai_ready)
        if not ready:
            return self._indexing.status(artifact_id, published_at=when, ai_ready=ready)
        return self._indexing.trigger(artifact_id, published_at=when, ai_ready=ready)

    def demo_document(self, artifact_id: str) -> tuple[str, bytes]:
        self.ensure_enabled()
        if self._publisher.mode != "demo":
            raise NotFoundError("Documents are opened in SharePoint.")
        return self._store.document(artifact_id)


__all__ = ["KnowledgeService", "DemoIndexing", "SearchIndexing"]
