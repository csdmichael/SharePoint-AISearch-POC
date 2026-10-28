"""Configuration loader.

Values come from the JSON files in app/api/config, from the shared governance files that sharedConfig points to, and
from environment overrides:

- API_CONFIG__<SECTION>__<KEY> overrides api.config.json, for example API_CONFIG__cors__allowedOrigins.
- API_AGENT__<SECTION>__<KEY> overrides agent.json, for example API_AGENT__foundry__accountName.

List values accept a comma-separated string or a JSON array. Missing or placeholder values stop the process at startup
with one ConfigError that lists every problem. Nothing tenant-specific is written into code.
"""

from __future__ import annotations

import json
import os
import re
import string
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.governance import Governance, GovernanceDefinitionError

API_ENV_PREFIX = "API_CONFIG__"
AGENT_ENV_PREFIX = "API_AGENT__"
PLACEHOLDER = re.compile(r"<[A-Za-z0-9_ .\-]+>")
GUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
TRUE_TEXT = frozenset({"true", "1", "yes", "on"})
FALSE_TEXT = frozenset({"false", "0", "no", "off"})
KNOWN_HANDLERS: frozenset[str] = frozenset(
    {
        "userAccess",
        "exposure",
        "brokenInheritance",
        "duplicates",
        "expiry",
        "ownership",
        "anomalies",
        "notifications",
        "backlog",
        "orphans",
        "conflicts",
        "help",
    }
)
KNOWN_ANOMALY_FEATURES: frozenset[str] = frozenset(
    {
        "daysSinceModified",
        "principalCount",
        "directGrantCount",
        "brokenInheritance",
        "anonymousLink",
        "everyoneClaim",
        "duplicateClusterSize",
    }
)
TEMPLATE_PLACEHOLDERS: frozenset[str] = frozenset(
    {"ownerName", "documentTitle", "documentUrl", "findingTitle", "reviewDate", "expirationDate", "reviewerName"}
)
PRINCIPAL_KINDS: frozenset[str] = frozenset({"user", "entraGroup", "sharePointGroup", "other"})
REQUIRED_API_PATHS: tuple[tuple[str, ...], ...] = (("auth", "audience"), ("auth", "clientId"))
REQUIRED_SEVERITY_TYPES: tuple[str, ...] = (
    "everyoneIncludingExternal",
    "everyoneExceptExternal",
    "anonymousLink",
    "organizationLink",
    "specificPeopleLink",
    "externalUserDirectGrant",
    "brokenInheritance",
    "orphanedAccount",
)
REQUIRED_EVERYONE_LABELS: tuple[str, ...] = ("includingExternal", "exceptExternal")
REQUIRED_LINK_LABELS: tuple[str, ...] = ("anonymous", "organization", "users")

# Placeholders each message may use. The code supplies exactly these names; a template that uses any other name fails
# at startup instead of failing while an answer is being written.
HYGIENE_REASON_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "conflictStatus": frozenset({"label"}),
    "duplicate": frozenset({"kind", "canonical"}),
    "expired": frozenset({"sources"}),
    "missingOwner": frozenset(),
    "lifecycleStatus": frozenset({"label"}),
    "dataQualityNot": frozenset({"status"}),
    "notRecorded": frozenset(),
    "reviewPassed": frozenset(),
}
EXPOSURE_DETAIL_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "everyoneHolds": frozenset({"principal", "role"}),
    "linkAccess": frozenset({"principal", "role"}),
    "externalGuest": frozenset({"upn", "role"}),
    "brokenInheritance": frozenset({"count"}),
    "orphanMissing": frozenset(),
    "orphanUnknown": frozenset(),
    "orphanDisabled": frozenset(),
}
NOTIFICATION_MESSAGE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "reviewerFallback": frozenset(),
    "ownerFallback": frozenset(),
    "missingValue": frozenset(),
    "unknownValue": frozenset(),
    "selectedFindingTitle": frozenset(),
    "selectedReason": frozenset(),
    "sendRefused": frozenset({"mode"}),
    "sendDelivery": frozenset(),
}
AGENT_MESSAGE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "foundryNotConfigured": frozenset(),
    "foundryNotRequested": frozenset(),
    "foundryUnavailable": frozenset({"reason"}),
    "foundryUnexpected": frozenset(),
    "signedInUser": frozenset(),
}
ANSWER_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "exposureSummary": frozenset({"count", "items"}),
    "exposureTypeLine": frozenset({"label", "count"}),
    "exposureExample": frozenset({"item", "path", "principal", "role", "severity"}),
    "userSummary": frozenset({"user", "items", "paths"}),
    "grantPathsLine": frozenset({"paths"}),
    "grantPathsNone": frozenset(),
    "grantPair": frozenset({"kind", "count"}),
    "groupsLine": frozenset({"groups"}),
    "brokenSummary": frozenset({"count"}),
    "brokenExample": frozenset({"item", "path", "grants"}),
    "grantName": frozenset({"principal", "role"}),
    "duplicatesLibrary": frozenset({"library", "exact", "near", "conflicts"}),
    "duplicateCluster": frozenset({"kind", "clusterId", "canonical", "canonicalName", "duplicates"}),
    "expirySummary": frozenset({"expired", "overdue"}),
    "expiredExample": frozenset({"title", "date", "sources"}),
    "reviewOverdueExample": frozenset({"title", "date"}),
    "ownershipSummary": frozenset({"count"}),
    "ownershipExample": frozenset({"title", "path"}),
    "anomalySummary": frozenset({"count"}),
    "anomalyExample": frozenset({"title", "score", "anomaly", "drivers"}),
    "notificationsSummary": frozenset({"count", "template", "mode"}),
    "notificationsSkipped": frozenset({"skipped"}),
    "skippedPair": frozenset({"reason", "count"}),
    "backlogSummary": frozenset({"severities"}),
    "backlogNone": frozenset(),
    "severityPair": frozenset({"severity", "count"}),
    "backlogFinding": frozenset({"title", "severity", "count", "libraries"}),
    "libraryPair": frozenset({"library", "count"}),
    "orphanSummary": frozenset({"count"}),
    "orphanExample": frozenset({"item", "path", "who", "status"}),
    "conflictsSummary": frozenset({"stored", "live"}),
    "conflictExample": frozenset({"first", "second", "similarity"}),
    "helpIntro": frozenset(),
    "helpExample": frozenset({"example"}),
}


class ConfigError(Exception):
    """Raised at startup. The message lists every problem found."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def template_problems(label: str, text: str, allowed: frozenset[str]) -> list[str]:
    """A message template must parse and use only the placeholders the code supplies for that message."""

    try:
        used = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError as exc:
        return [f"{label} is not a valid message template ({exc})"]
    unknown = sorted(used - allowed)
    if unknown:
        allowed_text = ", ".join(sorted(allowed)) or "none"
        return [f"{label} uses placeholders {unknown} that the code does not supply (allowed: {allowed_text})"]
    return []


def check_templates(model: _Model, allowed: Mapping[str, frozenset[str]]) -> None:
    problems: list[str] = []
    for name, placeholders in allowed.items():
        problems.extend(template_problems(f"{type(model).__name__}.{name}", getattr(model, name), placeholders))
    if problems:
        raise ValueError("; ".join(problems))


class ServerConfig(_Model):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class OpenApiConfig(_Model):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CorsConfig(_Model):
    allowedOrigins: list[str]
    allowedMethods: list[str] = Field(min_length=1)
    allowedHeaders: list[str] = Field(min_length=1)


class AuthConfig(_Model):
    audience: str = Field(min_length=1)
    requiredRole: str = Field(min_length=1)
    clientId: str = Field(min_length=1)
    authorityHostUrl: str = Field(pattern=r"^https://")
    jwksPath: str = Field(pattern=r"^/")
    validIssuerTemplate: str = Field(pattern=r"\{tenantId\}")
    clockSkewSeconds: int = Field(ge=0, le=3600)
    jwksCacheSeconds: int = Field(ge=60)
    jwksMinRefreshSeconds: int = Field(ge=0)


class IdentityConfig(_Model):
    managedIdentityClientId: str = ""
    graphScope: str = Field(min_length=1)
    sharePointScopeTemplate: str = Field(pattern=r"\{sharePointHost\}")
    tokenRefreshMarginSeconds: float = Field(ge=0)


class GraphConfig(_Model):
    baseUrl: str = Field(pattern=r"^https://")
    pageSize: int = Field(ge=1, le=999)
    timeoutSeconds: float = Field(gt=0)
    maxRetries: int = Field(ge=0, le=10)
    retryBackoffSeconds: float = Field(ge=0)
    maxRetryDelaySeconds: float = Field(gt=0)
    maxConcurrency: int = Field(ge=1, le=32)
    maxMembersPerGroup: int = Field(ge=1)


class CrawlConfig(_Model):
    maxItems: int = Field(ge=1)
    maxDepth: int = Field(ge=1)


class SharePointConfig(_Model):
    """libraryDisplayNames is an optional filter: empty (the default) lists every visible document library."""

    libraryDisplayNames: list[str] = Field(default_factory=list)
    pageSize: int = Field(ge=1, le=5000)
    maxSiteUsers: int = Field(ge=1)
    crawl: CrawlConfig
    principalTypes: dict[str, str]
    linkRoleNames: dict[str, str]
    defaultLinkRole: str = Field(min_length=1)
    systemFolderNames: list[str] = Field(default_factory=list)

    @field_validator("principalTypes")
    @classmethod
    def _known_principal_kinds(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = {code: kind for code, kind in value.items() if kind not in PRINCIPAL_KINDS}
        if unknown:
            raise ValueError(f"unknown principal kinds {unknown}; use one of {sorted(PRINCIPAL_KINDS)}")
        return value


class ApiSection(_Model):
    defaultPageSize: int = Field(ge=1)
    maxPageSize: int = Field(ge=1)
    sortableFields: list[str] = Field(min_length=1)
    defaultSort: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "ApiSection":
        if self.defaultPageSize > self.maxPageSize:
            raise ValueError("defaultPageSize cannot exceed maxPageSize")
        if self.defaultSort not in self.sortableFields:
            raise ValueError("defaultSort must be one of sortableFields")
        return self


class HygieneReasons(_Model):
    """Reason text for hygiene findings. Placeholders are listed in HYGIENE_REASON_PLACEHOLDERS."""

    conflictStatus: str = Field(min_length=1)
    duplicate: str = Field(min_length=1)
    expired: str = Field(min_length=1)
    missingOwner: str = Field(min_length=1)
    lifecycleStatus: str = Field(min_length=1)
    dataQualityNot: str = Field(min_length=1)
    notRecorded: str = Field(min_length=1)
    reviewPassed: str = Field(min_length=1)

    @model_validator(mode="after")
    def _placeholders(self) -> "HygieneReasons":
        check_templates(self, HYGIENE_REASON_PLACEHOLDERS)
        return self


class HygieneSection(_Model):
    asOfDate: date | None = None
    sampleSize: int = Field(ge=1, le=50)
    reasons: HygieneReasons


class CacheConfig(_Model):
    libraryTtlSeconds: int = Field(ge=0)
    membershipTtlSeconds: int = Field(ge=0)


class SharedConfigPaths(_Model):
    """Paths to the shared governance files. Relative paths resolve against the package root (the folder with config/)."""

    deploymentPath: str = Field(min_length=1)
    vocabularyPath: str = Field(min_length=1)
    policyPath: str = Field(min_length=1)


class ApiConfig(_Model):
    schemaVersion: str | None = None
    server: ServerConfig
    routePrefix: str = Field(pattern=r"^/")
    docsPath: str | None = None
    redocPath: str | None = None
    openapiPath: str | None = None
    openapi: OpenApiConfig
    cors: CorsConfig
    auth: AuthConfig
    identity: IdentityConfig
    graph: GraphConfig
    sharePoint: SharePointConfig
    api: ApiSection
    hygiene: HygieneSection
    cache: CacheConfig
    sharedConfig: SharedConfigPaths


class TfidfConfig(_Model):
    ngramRange: tuple[int, int]
    minDf: int | float = 1
    maxFeatures: int | None = None
    sublinearTf: bool = True

    @field_validator("ngramRange")
    @classmethod
    def _ngram(cls, value: tuple[int, int]) -> tuple[int, int]:
        low, high = value
        if low < 1 or high < low:
            raise ValueError("ngramRange must be [min >= 1, max >= min]")
        return value


class DuplicateConfig(_Model):
    cosineThreshold: float | None = Field(default=None, gt=0, le=1)
    distanceThreshold: float | None = Field(default=None, ge=0, lt=1)
    minClusterSize: int = Field(ge=2)
    linkage: Literal["average", "complete", "single"] = "average"


class AnomalyConfig(_Model):
    contamination: float = Field(gt=0, lt=0.5)
    nEstimators: int = Field(ge=10)
    randomState: int
    topN: int = Field(ge=1)
    features: list[str] = Field(min_length=1)

    @field_validator("features")
    @classmethod
    def _known_features(cls, value: list[str]) -> list[str]:
        unknown = [name for name in value if name not in KNOWN_ANOMALY_FEATURES]
        if unknown:
            raise ValueError(f"unknown anomaly features {unknown}")
        return value


class ExpiryConfig(_Model):
    datePatterns: list[str] = Field(min_length=1)
    textMaxChars: int = Field(ge=100)
    reviewOverdueGraceDays: int = Field(ge=0)

    @field_validator("datePatterns")
    @classmethod
    def _patterns_compile(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid date pattern {pattern!r}: {exc}") from None
            if "date" not in compiled.groupindex:
                raise ValueError(f"date pattern {pattern!r} must define a named group 'date'")
        return value


class ExposureDetails(_Model):
    """Finding text shown in exposure results. Placeholders are listed in EXPOSURE_DETAIL_PLACEHOLDERS."""

    everyoneHolds: str = Field(min_length=1)
    linkAccess: str = Field(min_length=1)
    externalGuest: str = Field(min_length=1)
    brokenInheritance: str = Field(min_length=1)
    orphanMissing: str = Field(min_length=1)
    orphanUnknown: str = Field(min_length=1)
    orphanDisabled: str = Field(min_length=1)

    @model_validator(mode="after")
    def _placeholders(self) -> "ExposureDetails":
        check_templates(self, EXPOSURE_DETAIL_PLACEHOLDERS)
        return self


class ExposureConfig(_Model):
    everyoneLoginPattern: str
    externalUserPattern: str
    anonymousLinkScopes: list[str] = Field(min_length=1)
    organizationLinkScopes: list[str] = Field(min_length=1)
    severities: dict[str, str]
    severityOrder: list[str] = Field(min_length=1)
    everyoneLabels: dict[str, str]
    linkLabels: dict[str, str]
    details: ExposureDetails

    @field_validator("everyoneLoginPattern", "externalUserPattern")
    @classmethod
    def _regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from None
        return value

    @model_validator(mode="after")
    def _labels_and_severities_defined(self) -> "ExposureConfig":
        for name, mapping, required in (
            ("severities", self.severities, REQUIRED_SEVERITY_TYPES),
            ("everyoneLabels", self.everyoneLabels, REQUIRED_EVERYONE_LABELS),
            ("linkLabels", self.linkLabels, REQUIRED_LINK_LABELS),
        ):
            absent = [key for key in required if key not in mapping]
            if absent:
                raise ValueError(f"{name} must define {', '.join(absent)}")
        return self


class ExtractionConfig(_Model):
    supportedExtensions: list[str] = Field(min_length=1)
    maxFileBytes: int = Field(ge=1)


class LoginNamePatterns(_Model):
    user: str
    entraGroup: str
    sharePointGroup: str
    everyoneClaim: str
    sharingLink: str

    @field_validator("*")
    @classmethod
    def _regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from None
        return value


class AnalyticsConfig(_Model):
    schemaVersion: str | None = None
    tfidf: TfidfConfig
    duplicates: DuplicateConfig
    anomaly: AnomalyConfig
    expiry: ExpiryConfig
    exposure: ExposureConfig
    extraction: ExtractionConfig
    loginNamePatterns: LoginNamePatterns


class NotificationTemplate(_Model):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)

    @model_validator(mode="after")
    def _known_placeholders(self) -> "NotificationTemplate":
        found = set(re.findall(r"\{([A-Za-z]+)\}", self.subject + " " + self.body))
        unknown = sorted(found - TEMPLATE_PLACEHOLDERS)
        if unknown:
            raise ValueError(f"unknown template placeholders {unknown}")
        return self


class SenderConfig(_Model):
    userPrincipalName: str = ""


class NotificationMessages(_Model):
    """Text the notification service writes. Placeholders are listed in NOTIFICATION_MESSAGE_PLACEHOLDERS."""

    reviewerFallback: str = Field(min_length=1)
    ownerFallback: str = Field(min_length=1)
    missingValue: str = Field(min_length=1)
    unknownValue: str = Field(min_length=1)
    selectedFindingTitle: str = Field(min_length=1)
    selectedReason: str = Field(min_length=1)
    sendRefused: str = Field(min_length=1)
    sendDelivery: str = Field(min_length=1)

    @model_validator(mode="after")
    def _placeholders(self) -> "NotificationMessages":
        check_templates(self, NOTIFICATION_MESSAGE_PLACEHOLDERS)
        return self


class NotificationsConfig(_Model):
    schemaVersion: str | None = None
    mode: Literal["dryRun", "sendAsReviewer"]
    outboxPath: str = Field(min_length=1)
    sender: SenderConfig
    maxPerBatch: int = Field(ge=1)
    dedupeWindowHours: int = Field(ge=0)
    templates: dict[str, NotificationTemplate]
    messages: NotificationMessages


class FoundryConfig(_Model):
    enabled: bool
    projectEndpointTemplate: str = Field(pattern=r"^https://")
    accountName: str | None = None
    projectName: str | None = None
    agentName: str | None = None
    tokenScope: str = Field(min_length=1)
    responsesPath: str = Field(min_length=1)
    timeoutSeconds: float = Field(gt=0)
    maxRetries: int = Field(ge=0, le=5)
    retryBackoffSeconds: float = Field(ge=0)


class IntentConfig(_Model):
    id: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    handler: str

    @field_validator("handler")
    @classmethod
    def _known_handler(cls, value: str) -> str:
        if value not in KNOWN_HANDLERS:
            raise ValueError(f"unknown handler '{value}'")
        return value


class AgentMessages(_Model):
    """Status text for the agent answer. Placeholders are listed in AGENT_MESSAGE_PLACEHOLDERS."""

    foundryNotConfigured: str = Field(min_length=1)
    foundryNotRequested: str = Field(min_length=1)
    foundryUnavailable: str = Field(min_length=1)
    foundryUnexpected: str = Field(min_length=1)
    signedInUser: str = Field(min_length=1)

    @model_validator(mode="after")
    def _placeholders(self) -> "AgentMessages":
        check_templates(self, AGENT_MESSAGE_PLACEHOLDERS)
        return self


class AgentLimits(_Model):
    maxExamples: int = Field(ge=1, le=50)
    maxConversations: int = Field(ge=1, le=10000)
    maxTurnsPerConversation: int = Field(ge=1, le=1000)
    maxEvidenceChars: int = Field(ge=1000, le=1000000)


class DraftNotificationConfig(_Model):
    """The notification template and hygiene finding the owner-notification intent drafts from."""

    templateId: str = Field(min_length=1)
    findingId: str = Field(min_length=1)


class AgentFindingIds(_Model):
    """Hygiene finding ids (from the governance vocabulary) that evidence handlers read."""

    missingOwners: str = Field(min_length=1)
    conflictingAuthoritative: str = Field(min_length=1)
    conflictsWithAuthoritative: str = Field(min_length=1)


class AnswerText(_Model):
    """Sentences the evidence handlers write. Placeholders are listed in ANSWER_PLACEHOLDERS."""

    exposureSummary: str = Field(min_length=1)
    exposureTypeLine: str = Field(min_length=1)
    exposureExample: str = Field(min_length=1)
    userSummary: str = Field(min_length=1)
    grantPathsLine: str = Field(min_length=1)
    grantPathsNone: str = Field(min_length=1)
    grantPair: str = Field(min_length=1)
    groupsLine: str = Field(min_length=1)
    brokenSummary: str = Field(min_length=1)
    brokenExample: str = Field(min_length=1)
    grantName: str = Field(min_length=1)
    duplicatesLibrary: str = Field(min_length=1)
    duplicateCluster: str = Field(min_length=1)
    expirySummary: str = Field(min_length=1)
    expiredExample: str = Field(min_length=1)
    reviewOverdueExample: str = Field(min_length=1)
    ownershipSummary: str = Field(min_length=1)
    ownershipExample: str = Field(min_length=1)
    anomalySummary: str = Field(min_length=1)
    anomalyExample: str = Field(min_length=1)
    notificationsSummary: str = Field(min_length=1)
    notificationsSkipped: str = Field(min_length=1)
    skippedPair: str = Field(min_length=1)
    backlogSummary: str = Field(min_length=1)
    backlogNone: str = Field(min_length=1)
    severityPair: str = Field(min_length=1)
    backlogFinding: str = Field(min_length=1)
    libraryPair: str = Field(min_length=1)
    orphanSummary: str = Field(min_length=1)
    orphanExample: str = Field(min_length=1)
    conflictsSummary: str = Field(min_length=1)
    conflictExample: str = Field(min_length=1)
    helpIntro: str = Field(min_length=1)
    helpExample: str = Field(min_length=1)

    @model_validator(mode="after")
    def _placeholders(self) -> "AnswerText":
        check_templates(self, ANSWER_PLACEHOLDERS)
        return self


class AgentConfig(_Model):
    schemaVersion: str | None = None
    foundry: FoundryConfig
    evidenceLimit: int = Field(ge=1, le=200)
    limits: AgentLimits
    fallbackIntent: str = Field(min_length=1)
    draftNotification: DraftNotificationConfig
    findingIds: AgentFindingIds
    instructions: str = Field(min_length=1)
    intents: list[IntentConfig] = Field(min_length=1)
    messages: AgentMessages
    answers: AnswerText

    @model_validator(mode="after")
    def _intents_consistent(self) -> "AgentConfig":
        ids = [intent.id for intent in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("intent ids must be unique")
        if self.fallbackIntent not in ids:
            raise ValueError("fallbackIntent must match one of the intent ids")
        return self


class PromptItem(_Model):
    id: str = Field(min_length=1)
    issueId: str = Field(min_length=1)
    issueLabel: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PromptCatalog(_Model):
    schemaVersion: str = Field(min_length=1)
    provisional: bool
    note: str = Field(min_length=1)
    placeholders: dict[str, str] = Field(default_factory=dict)
    prompts: list[PromptItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "PromptCatalog":
        ids = [prompt.id for prompt in self.prompts]
        if len(ids) != len(set(ids)):
            raise ValueError("prompt ids must be unique")
        return self


class _SharedModel(BaseModel):
    """The shared governance deployment file is read for tenant and site values only. Other sections are ignored."""

    model_config = ConfigDict(extra="ignore")


class SharedAzure(_SharedModel):
    tenantId: str = Field(pattern=GUID_PATTERN)


class SharedSharePoint(_SharedModel):
    siteUrl: str = Field(pattern=r"^https://")
    siteDisplayName: str | None = None
    sites: list["SharedSiteEntry"] = Field(default_factory=list)


class SharedSiteEntry(_SharedModel):
    siteId: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    displayName: str = Field(min_length=1)
    siteUrl: str = Field(pattern=r"^https://")
    function: str | None = None


class SharedDeployment(_SharedModel):
    azure: SharedAzure
    sharePoint: SharedSharePoint


@dataclass(frozen=True)
class SiteSettings:
    site_id: str
    display_name: str
    function: str | None
    site_url: str
    host: str
    server_relative_path: str
    tenant_id: str


@dataclass(frozen=True)
class FoundryTarget:
    enabled: bool
    endpoint: str | None
    account_name: str | None
    project_name: str | None
    agent_name: str | None
    token_scope: str
    responses_path: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.endpoint) and bool(self.agent_name)


@dataclass(frozen=True)
class Settings:
    config_path: Path
    service_root: Path
    api: ApiConfig
    analytics: AnalyticsConfig
    notifications: NotificationsConfig
    agent: AgentConfig
    prompts: PromptCatalog
    governance: Governance
    site: SiteSettings
    site_catalog: tuple[SiteSettings, ...]
    foundry: FoundryTarget
    outbox_path: Path
    applied_overrides: tuple[str, ...]


T = TypeVar("T", bound=_Model)


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise ConfigError(f"{label}: file not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from None


def _read_object(path: Path, label: str) -> dict[str, Any]:
    data = _read_json(path, label)
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: the top level must be a JSON object")
    return data


def _validate(model: type[T], data: Any, label: str) -> T:
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: the top level must be a JSON object")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        lines = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "(root)"
            lines.append(f"{label}: {location}: {error['msg']}")
        raise ConfigError("\n".join(lines)) from None


def _node_get(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for segment in path:
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


def _is_unset(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or PLACEHOLDER.search(value) is not None
    return False


def _env_name(path: tuple[str, ...], prefix: str) -> str:
    return prefix + "__".join(path)


def _leaves(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Yields (dotted path, text) for every string in the document. List items report their parent's path."""

    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _leaves(value, (*path, str(key)))
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value, path)
    elif isinstance(node, str):
        yield path, node


def check_resolved(data: Mapping[str, Any], required: tuple[tuple[str, ...], ...], label: str, prefix: str) -> None:
    """Fails when a required value is empty, or when any value still holds a <PLACEHOLDER> from the repo file."""

    problems: list[str] = []
    reported: set[tuple[str, ...]] = set()
    for path in required:
        value = _node_get(data, path)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(
                f"{label}: {'.'.join(path)} is not set. Set it in the file or export {_env_name(path, prefix)}."
            )
            reported.add(path)
    for path, text in _leaves(data):
        if path in reported:
            continue
        found = PLACEHOLDER.search(text)
        if found is not None:
            problems.append(
                f"{label}: {'.'.join(path)} still contains the placeholder {found.group(0)}. "
                f"Replace it in the file or export {_env_name(path, prefix)}."
            )
    if problems:
        raise ConfigError("\n".join(dict.fromkeys(problems)))


def _match_key(node: Mapping[str, Any], segment: str, override: str, label: str) -> str:
    wanted = segment.lower()
    for key in node:
        if key.lower() == wanted:
            return key
    raise ConfigError(f"{label}: environment override {override} does not match a configuration key")


def _coerce_list(text: str, override: str, label: str) -> list[str]:
    """Comma-separated text ("a,b,c"; empty means no items). Items that contain commas need a JSON array ("[...]")."""

    stripped = text.strip()
    if not stripped.startswith("["):
        return [item.strip() for item in stripped.split(",") if item.strip()]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        raise ConfigError(f"{label}: {override} must be a JSON array or a comma-separated list") from None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ConfigError(f"{label}: {override} must be a JSON array or a comma-separated list")
    return parsed


def _coerce(text: str, current: Any, override: str, label: str) -> Any:
    if isinstance(current, bool):
        lowered = text.strip().lower()
        if lowered in TRUE_TEXT:
            return True
        if lowered in FALSE_TEXT:
            return False
        raise ConfigError(f"{label}: {override} must be true or false")
    if isinstance(current, int):
        try:
            return int(text)
        except ValueError:
            raise ConfigError(f"{label}: {override} must be an integer") from None
    if isinstance(current, float):
        try:
            return float(text)
        except ValueError:
            raise ConfigError(f"{label}: {override} must be a number") from None
    if isinstance(current, list):
        return _coerce_list(text, override, label)
    if isinstance(current, dict):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise ConfigError(f"{label}: {override} must be a JSON object") from None
        if not isinstance(parsed, dict):
            raise ConfigError(f"{label}: {override} must be a JSON object")
        return parsed
    if current is None and not text.strip():
        return None
    return text.strip()


def apply_env_overrides(data: dict[str, Any], env: Mapping[str, str], label: str, prefix: str) -> tuple[str, ...]:
    """Applies every variable whose name starts with prefix. '__' separates the path segments; keys match case-insensitively."""

    applied: list[str] = []
    for name in sorted(env):
        if not name.upper().startswith(prefix):
            continue
        segments = name[len(prefix):].split("__")
        if not all(segments):
            raise ConfigError(f"{label}: environment override {name} has an empty path segment")
        node: dict[str, Any] = data
        for segment in segments[:-1]:
            key = _match_key(node, segment, name, label)
            if not isinstance(node[key], dict):
                raise ConfigError(f"{label}: environment override {name} points inside a non-object value")
            node = node[key]
        leaf = _match_key(node, segments[-1], name, label)
        node[leaf] = _coerce(env[name], node[leaf], name, label)
        applied.append(name)
    return tuple(applied)


def resolve_path(base: Path, configured: str) -> Path:
    """Resolves a configured path. Both '/' and '\\' are accepted, so one value works on Windows and Linux.

    Relative paths resolve against base (the package root: the folder that contains config/). Absolute paths are used
    as given.
    """

    normalized = configured.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate.resolve()
    return (base / candidate).resolve()


def _site_settings(
    *,
    tenant_id: str,
    site_id: str,
    display_name: str,
    site_url: str,
    function: str | None,
) -> SiteSettings:
    parts = urlsplit(site_url)
    path = parts.path.rstrip("/")
    if not path:
        raise ConfigError("trusted-knowledge.json: sharePoint.siteUrl must include the site path, e.g. /sites/<name>")
    return SiteSettings(
        site_id=site_id,
        display_name=display_name,
        function=function.strip() if isinstance(function, str) and function.strip() else None,
        site_url=f"{parts.scheme}://{parts.netloc}{path}",
        host=parts.netloc,
        server_relative_path=path,
        tenant_id=tenant_id,
    )


def _site_catalog(deployment: SharedDeployment) -> tuple[SiteSettings, ...]:
    tenant_id = deployment.azure.tenantId
    fallback_url = deployment.sharePoint.siteUrl
    fallback_name = deployment.sharePoint.siteDisplayName or "Default site"
    entries: list[SiteSettings] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    for entry in deployment.sharePoint.sites:
        site = _site_settings(
            tenant_id=tenant_id,
            site_id=entry.siteId.strip().lower(),
            display_name=entry.displayName.strip(),
            site_url=entry.siteUrl,
            function=entry.function,
        )
        if site.site_id in seen_ids:
            raise ConfigError(f"trusted-knowledge.json: duplicate sharePoint.sites siteId '{site.site_id}'")
        if site.site_url in seen_urls:
            raise ConfigError(f"trusted-knowledge.json: duplicate sharePoint.sites siteUrl '{site.site_url}'")
        seen_ids.add(site.site_id)
        seen_urls.add(site.site_url)
        entries.append(site)

    fallback_site = _site_settings(
        tenant_id=tenant_id,
        site_id="default",
        display_name=fallback_name.strip() if fallback_name.strip() else "Default site",
        site_url=fallback_url,
        function=None,
    )
    if fallback_site.site_url not in seen_urls:
        entries.insert(0, fallback_site)

    if not entries:
        raise ConfigError("trusted-knowledge.json: no SharePoint sites were configured")
    return tuple(entries)


def _foundry_target(config: FoundryConfig) -> FoundryTarget:
    """Only agent.json (and its API_AGENT__ overrides) selects the governance agent. Nothing else is used as a fallback."""

    endpoint = None
    if config.accountName and config.projectName:
        endpoint = config.projectEndpointTemplate.replace("{accountName}", config.accountName).replace(
            "{projectName}", config.projectName
        )
    return FoundryTarget(
        enabled=config.enabled,
        endpoint=endpoint,
        account_name=config.accountName,
        project_name=config.projectName,
        agent_name=config.agentName,
        token_scope=config.tokenScope,
        responses_path=config.responsesPath.lstrip("/"),
        timeout_seconds=config.timeoutSeconds,
        max_retries=config.maxRetries,
        retry_backoff_seconds=config.retryBackoffSeconds,
    )


def load_settings(config_path: str | Path, env: Mapping[str, str] | None = None) -> Settings:
    """Read, override and validate every configuration file. Raises ConfigError on any problem."""

    environment: Mapping[str, str] = os.environ if env is None else env
    config_file = Path(config_path).resolve()
    config_dir = config_file.parent
    service_root = config_dir.parent

    api_raw = _read_object(config_file, "api.config.json")
    applied = list(apply_env_overrides(api_raw, environment, "api.config.json", API_ENV_PREFIX))
    check_resolved(api_raw, REQUIRED_API_PATHS, "api.config.json", API_ENV_PREFIX)
    api = _validate(ApiConfig, api_raw, "api.config.json")

    analytics = _validate(AnalyticsConfig, _read_json(config_dir / "analytics.json", "analytics.json"), "analytics.json")

    notifications = _validate(
        NotificationsConfig, _read_json(config_dir / "notifications.json", "notifications.json"), "notifications.json"
    )
    if notifications.mode == "sendAsReviewer" and _is_unset(notifications.sender.userPrincipalName):
        raise ConfigError("notifications.json: sender.userPrincipalName must be set when mode is sendAsReviewer")

    agent_raw = _read_object(config_dir / "agent.json", "agent.json")
    applied.extend(apply_env_overrides(agent_raw, environment, "agent.json", AGENT_ENV_PREFIX))
    check_resolved(agent_raw, (), "agent.json", AGENT_ENV_PREFIX)
    agent = _validate(AgentConfig, agent_raw, "agent.json")

    prompts = _validate(
        PromptCatalog, _read_json(config_dir / "agent-prompts.json", "agent-prompts.json"), "agent-prompts.json"
    )
    intent_ids = {intent.id for intent in agent.intents}
    unknown_prompt_intents = sorted({prompt.intent for prompt in prompts.prompts} - intent_ids)
    if unknown_prompt_intents:
        raise ConfigError(f"agent-prompts.json: intents {unknown_prompt_intents} are not defined in agent.json")

    deployment_path = resolve_path(service_root, api.sharedConfig.deploymentPath)
    deployment = _validate(SharedDeployment, _read_object(deployment_path, "shared deployment file"),
                           deployment_path.name)
    vocabulary_path = resolve_path(service_root, api.sharedConfig.vocabularyPath)
    policy_path = resolve_path(service_root, api.sharedConfig.policyPath)
    try:
        governance = Governance(
            _read_object(vocabulary_path, "governance vocabulary"),
            _read_object(policy_path, "governance policy"),
        )
    except GovernanceDefinitionError as exc:
        raise ConfigError(str(exc)) from None

    finding_ids = {str(item["id"]) for item in governance.findings}
    referenced = {
        "agent.json: findingIds.missingOwners": agent.findingIds.missingOwners,
        "agent.json: findingIds.conflictingAuthoritative": agent.findingIds.conflictingAuthoritative,
        "agent.json: findingIds.conflictsWithAuthoritative": agent.findingIds.conflictsWithAuthoritative,
        "agent.json: draftNotification.findingId": agent.draftNotification.findingId,
    }
    problems = [
        f"{label} '{value}' is not a hygiene finding in the governance vocabulary"
        for label, value in referenced.items()
        if value not in finding_ids
    ]
    if agent.draftNotification.templateId not in notifications.templates:
        problems.append(
            f"agent.json: draftNotification.templateId '{agent.draftNotification.templateId}' "
            "is not a template in notifications.json"
        )
    if problems:
        raise ConfigError("\n".join(problems))

    site_catalog = _site_catalog(deployment)
    default_site_url = _site_settings(
        tenant_id=deployment.azure.tenantId,
        site_id="default",
        display_name=deployment.sharePoint.siteDisplayName or "Default site",
        site_url=deployment.sharePoint.siteUrl,
        function=None,
    ).site_url
    default_site = next((site for site in site_catalog if site.site_url == default_site_url), site_catalog[0])

    return Settings(
        config_path=config_file,
        service_root=service_root,
        api=api,
        analytics=analytics,
        notifications=notifications,
        agent=agent,
        prompts=prompts,
        governance=governance,
        site=default_site,
        site_catalog=site_catalog,
        foundry=_foundry_target(agent.foundry),
        outbox_path=resolve_path(service_root, notifications.outboxPath),
        applied_overrides=tuple(applied),
    )
