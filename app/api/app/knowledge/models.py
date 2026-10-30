"""Typed shapes of the Save to Knowledge workflow: the model output, the editable draft, the publish request."""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HTML_TAG = re.compile(r"<[^>]+>")

ORIGIN_SOURCE = "source"
ORIGIN_AI = "ai"
ORIGIN_DEFAULT = "default"
ORIGIN_UNKNOWN = "unknown"
Origin = Literal["source", "ai", "default", "unknown"]

# Content comes from what the conversation says; metadata is the model's suggestion; the owner defaults to the caller.
CONTENT_FIELDS: tuple[str, ...] = (
    "title", "executiveSummary", "issueContext", "rootCause", "decision", "recommendedAction", "keyFacts",
    "sourceDescription",
)
METADATA_FIELDS: tuple[str, ...] = ("category", "department", "product", "sensitivity", "reviewDate", "tags")
OWNER_FIELD = "owner"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ARTIFACT_ID_PATTERN = re.compile(r"^[A-Z0-9]{2,8}-[A-Z0-9]{4,32}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FieldOrigin(_Strict):
    field: str
    origin: Origin


class KnowledgeExtraction(_Strict):
    """What the model must return (structured output). Anything the conversation does not state is null or empty."""

    title: str = Field(min_length=1, max_length=300)
    executiveSummary: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1, max_length=80)
    issueContext: str | None = None
    rootCause: str | None = None
    decision: str | None = None
    recommendedAction: str | None = None
    keyFacts: list[str] = Field(default_factory=list, max_length=30)
    department: str | None = None
    product: str | None = None
    owner: str | None = None
    sourceDescription: str | None = None
    sensitivity: str = Field(min_length=1, max_length=40)
    suggestedReviewDate: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    fieldOrigins: list[FieldOrigin] = Field(default_factory=list)

    @field_validator("suggestedReviewDate")
    @classmethod
    def _iso_date(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("suggestedReviewDate must be an ISO date (YYYY-MM-DD) or null") from None
        return value.strip()


class ChatMessageIn(_Strict):
    id: str = Field(min_length=1, max_length=64)
    author: str = Field(min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    text: str = Field(min_length=1, max_length=8000)
    postedAt: str | None = Field(default=None, max_length=40)

    @field_validator("text")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        """Teams can hand over HTML. Only the visible text is kept."""

        text = re.sub(r"\s+", " ", html.unescape(HTML_TAG.sub(" ", value))).strip()
        if not text:
            raise ValueError("the message has no text")
        return text


class ExtractRequest(_Strict):
    conversationId: str | None = Field(default=None, max_length=64)
    sourceDescription: str | None = Field(default=None, max_length=300)
    messages: list[ChatMessageIn] = Field(min_length=1)


class KnowledgeDraft(_Strict):
    """The editable review form. `origins` says, per field, whether it came from the source, the model or a default."""

    title: str = ""
    executiveSummary: str = ""
    category: str = ""
    issueContext: str = ""
    rootCause: str = ""
    decision: str = ""
    recommendedAction: str = ""
    keyFacts: list[str] = Field(default_factory=list)
    department: str = ""
    product: str = ""
    ownerName: str = ""
    ownerUpn: str = ""
    ownerMention: str = ""
    sourceType: str = ""
    sourceDescription: str = ""
    sensitivity: str = ""
    reviewDate: str = ""
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "Draft"
    origins: dict[str, Origin] = Field(default_factory=dict)


class ExtractResponse(_Strict):
    draft: KnowledgeDraft
    provider: str
    providerLabel: str
    demo: bool
    messageCount: int
    warnings: list[str] = Field(default_factory=list)


class PublishRequest(_Strict):
    """The reviewed draft. The user's edits are authoritative; `attested` records the explicit publish decision."""

    title: str = Field(min_length=1, max_length=300)
    executiveSummary: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1, max_length=80)
    issueContext: str = Field(default="", max_length=4000)
    rootCause: str = Field(default="", max_length=4000)
    decision: str = Field(default="", max_length=4000)
    recommendedAction: str = Field(default="", max_length=4000)
    keyFacts: list[str] = Field(default_factory=list, max_length=30)
    department: str = Field(default="", max_length=120)
    product: str = Field(default="", max_length=120)
    ownerName: str = Field(default="", max_length=200)
    ownerUpn: str = Field(min_length=3, max_length=320)
    sourceType: str = Field(default="", max_length=80)
    sourceDescription: str = Field(default="", max_length=600)
    sensitivity: str = Field(min_length=1, max_length=40)
    reviewDate: str = Field(min_length=10, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=0.0, ge=0, le=1)
    extractionProvider: str = Field(default="manual", max_length=40)
    selectedMessageCount: int = Field(default=0, ge=0, le=500)
    authoritative: bool = True
    attested: bool = False

    @field_validator("keyFacts", "tags")
    @classmethod
    def _drop_blank(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]


class Location(_Strict):
    mode: Literal["graph", "demo"]
    siteName: str
    libraryName: str
    folder: str
    webUrl: str | None = None


class IndexingStatus(_Strict):
    stage: Literal["notReady", "published", "indexing", "available", "delayed", "failed"]
    message: str
    mode: Literal["search", "demo"]
    indexer: str | None = None
    checkedAt: str
    canTrigger: bool = True


class PublishResult(_Strict):
    artifactId: str
    title: str
    fileName: str
    category: str
    ownerName: str
    ownerUpn: str
    publishedAt: str
    reviewDate: str
    lifecycleStatus: str
    authoritative: bool
    aiReady: bool
    aiReadyBlockers: list[str] = Field(default_factory=list)
    trustScore: int
    location: Location
    demo: bool
    appliedFields: dict[str, str | int | bool] = Field(default_factory=dict)
    skippedFields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    indexing: IndexingStatus
