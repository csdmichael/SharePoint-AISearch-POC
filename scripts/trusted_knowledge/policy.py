"""Loads, validates and exposes the Trusted Knowledge governance policy and vocabulary.

The caller supplies both JSON files. governance-policy.json owns SharePoint columns, search index
fields, eligibility, similarity thresholds and trust weights. governance-vocabulary.json owns the
logical keys, display labels, message templates, classification, hygiene and retrieval text.
Code refers to logical keys and reads every configurable value through the accessors below.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

# Logical keys the code reads. The display text behind each key must come from the vocabulary.
REQUIRED_LABELS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "lifecycleStatus": ("draft", "published", "superseded", "archived"),
    "dataQualityStatus": ("good", "needsReview", "stale", "duplicate", "conflicting"),
    "conflictStatus": ("none", "conflictingAuthoritative", "conflictsWithAuthoritative"),
    "duplicateKind": ("exact", "near"),
})
# Label groups whose values must be choices of the SharePoint column with the same logical key.
CHOICE_LABEL_GROUPS = ("lifecycleStatus", "dataQualityStatus", "conflictStatus", "sensitivity")
CLASSIFICATION_KEYS = ("documentType", "processArea", "sensitivity")
BLOCKER_KEYS = (
    "lifecycleNotRequired", "notAuthoritative", "ownerMissing", "reviewMissing", "reviewPassed",
    "expirationPassed", "effectiveInFuture", "duplicateOf", "sensitivityNotTrusted", "sourceNotApproved",
)
EXCLUSION_KEYS = (
    "lifecycle", "notAuthoritative", "duplicate", "expired", "reviewPassed", "conflictsWithAuthoritative",
    "notAiReady",
)
REQUIRED_MESSAGES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "trustReasons": ("total",),
    "blockers": BLOCKER_KEYS,
    "duplicate": ("exact", "near"),
    "conflict": ("candidate",),
    "exclusions": EXCLUSION_KEYS,
})
REQUIRED_RETRIEVAL: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "routing": ("trustedTool", "governanceTool", "governanceKeywords"),
    "filterTemplates": ("equalsText", "equalsBoolean", "combine", "anyOf", "group"),
    "statuses": ("trusted", "conflict", "noSource"),
    "banners": ("conflict", "noSource"),
    "cardTitles": ("trusted", "conflict"),
    "cardLabels": (
        "source", "status", "authoritative", "knowledgeOwner", "reviewDate", "trustScore", "whyTrusted",
        "citation", "missing", "notEligible", "yes", "no",
    ),
    "whyTrustedTokens": ("published", "authoritative", "current", "owned", "validated", "joiner"),
})
# Hygiene rule -> label group of its finding value. None marks a rule that takes no value.
FINDING_RULES: Mapping[str, str | None] = MappingProxyType({
    "conflictStatus": "conflictStatus",
    "duplicateKind": "duplicateKind",
    "lifecycleStatus": "lifecycleStatus",
    "dataQualityNot": "dataQualityStatus",
    "expired": None,
    "missingOwner": None,
})
_MISSING = object()


@dataclass(frozen=True)
class HygieneMetric:
    key: str
    label: str


@dataclass(frozen=True)
class HygieneFinding:
    id: str
    title: str
    severity: str
    rule: str
    value: str | None


class Policy:
    """Validated governance policy and vocabulary. Accessors return immutable values or fresh copies."""

    def __init__(self, policy: Mapping[str, Any], vocabulary: Mapping[str, Any]) -> None:
        self._policy: Mapping[str, Any] = _freeze(policy)
        self._vocabulary: Mapping[str, Any] = _freeze(vocabulary)
        self._columns: dict[str, Mapping[str, Any]] = {}
        self._index_fields: list[str] = []
        self._projection: dict[str, str] = {}
        self._field_by_column: dict[str, str] = {}
        self._number_pattern: re.Pattern[str] | None = None
        self._whitespace_pattern: re.Pattern[str] | None = None
        self._validate_policy()
        self._validate_vocabulary()

    @classmethod
    def load(cls, policy_path: str | Path, vocabulary_path: str | Path) -> Policy:
        return cls(_read_json(policy_path), _read_json(vocabulary_path))

    def column(self, key: str) -> str:
        """SharePoint column name for a logical column key."""
        return self._vocabulary_text(f"columns.{key}", "column")

    def index_field(self, key: str) -> str:
        """Search index field for a logical key from the vocabulary indexFields block."""
        return self._vocabulary_text(f"indexFields.{key}", "index field")

    def search_field(self, key: str) -> str:
        """Search index field for a logical column key, through searchProjection."""
        if _lookup(self._vocabulary, f"indexFields.{key}") is not _MISSING:
            return self.index_field(key)
        column = self.column(key)
        if column not in self._field_by_column:
            raise ValueError(f"Column {column} is not projected to the search index.")
        return self._field_by_column[column]

    def search_projection(self) -> tuple[tuple[str, str], ...]:
        """(search index field, SharePoint column) pairs in policy order."""
        return tuple(self._projection.items())

    def label(self, group: str, key: str) -> str:
        return self._vocabulary_text(f"labels.{group}.{key}", "label")

    def message(self, group: str, *keys: str) -> str:
        return self._vocabulary_text(".".join(("messages", group, *keys)), "message")

    def render(self, template: str, **values: Any) -> str:
        try:
            return template.format(**values)
        except KeyError as error:
            raise ValueError(f"Message template {template!r} needs a value for {error.args[0]!r}.") from error

    def choices(self, column_key: str) -> tuple[str, ...]:
        name = self.column(column_key)
        column = self._columns.get(name)
        if column is None or "choice" not in column:
            raise ValueError(f"{name} is not a choice column in sharePointColumns.")
        return tuple(column["choice"]["choices"])

    def trust_weights(self) -> dict[str, Any]:
        return dict(self._policy_path("trustScore.weights"))

    def trust_penalties(self) -> dict[str, Any]:
        return dict(self._policy_path("trustScore.penalties"))

    def trust_weight(self, key: str) -> Any:
        return self._policy_path(f"trustScore.weights.{key}")

    def trust_penalty(self, key: str) -> Any:
        return self._policy_path(f"trustScore.penalties.{key}")

    def trust_bounds(self) -> tuple[Any, Any]:
        return self._policy_path("trustScore.minScore"), self._policy_path("trustScore.maxScore")

    def required_lifecycle(self) -> str:
        return self._policy_path("eligibility.lifecycleStatus")

    def required_authoritative(self) -> bool:
        return self._policy_path("eligibility.authoritative")

    def trusted_sensitivity(self) -> tuple[str, ...]:
        return tuple(self._policy_path("eligibility.trustedSensitivity"))

    def approved_source_systems(self) -> tuple[str, ...]:
        return tuple(self._policy_path("eligibility.approvedSourceSystems"))

    def authoritative_claim_label(self) -> str:
        return self.label("lifecycleStatus", self._vocabulary_path("rules.authoritativeClaimLifecycleKey"))

    def stale_lifecycle_labels(self) -> tuple[str, ...]:
        return tuple(self.label("lifecycleStatus", key) for key in self._vocabulary_path("rules.staleLifecycleKeys"))

    def required_when_published(self) -> tuple[str, ...]:
        return tuple(self._policy_path("publishRequirements.requiredWhenPublished"))

    def near_duplicate_cosine(self) -> float:
        return self._policy_number("similarity.nearDuplicateCosine")

    def conflict_candidate_cosine(self) -> float:
        return self._policy_number("similarity.conflictCandidateCosine")

    def embedding_character_limit(self) -> int:
        return self._policy_path("similarity.embeddingCharacterLimit")

    def number_pattern(self) -> re.Pattern[str]:
        return self._number_pattern

    def whitespace_pattern(self) -> re.Pattern[str]:
        return self._whitespace_pattern

    def hash_algorithm(self) -> str:
        return self._policy_path("similarity.hashAlgorithm")

    def classification_default(self, key: str) -> str:
        return self._classification(key)["default"]

    def classification_rules(self, key: str) -> tuple[tuple[str, str], ...]:
        return tuple((rule["keyword"], rule["value"]) for rule in self._classification(key)["rules"])

    def product_family_matches_choices(self) -> bool:
        return self._vocabulary_path("classification.productFamilyMatchesChoices")

    def suggestion_defaults(self) -> dict[str, Any]:
        return dict(self._vocabulary_path("classification.suggestionDefaults"))

    def requires_owner_review(self) -> bool:
        """Workflow flag for owner review. It is not a SharePoint column, so suggestions omit it."""
        return self._vocabulary_path("classification.suggestionDefaults.requiresOwnerReview")

    def hygiene_metrics(self) -> tuple[HygieneMetric, ...]:
        return tuple(
            HygieneMetric(key=metric["key"], label=metric["label"])
            for metric in self._vocabulary_path("hygiene.metrics")
        )

    def hygiene_findings(self) -> tuple[HygieneFinding, ...]:
        return tuple(
            HygieneFinding(
                id=finding["id"],
                title=finding["title"],
                severity=finding["severity"],
                rule=finding["rule"],
                value=finding.get("value"),
            )
            for finding in self._vocabulary_path("hygiene.findings")
        )

    def retrieval_block(self) -> Mapping[str, Any]:
        return self._vocabulary_path("retrieval")

    def _classification(self, key: str) -> Mapping[str, Any]:
        if key not in CLASSIFICATION_KEYS:
            raise ValueError(f"Unknown classification {key}.")
        return self._vocabulary_path(f"classification.{key}")

    def _vocabulary_text(self, path: str, kind: str) -> str:
        value = _lookup(self._vocabulary, path)
        if not isinstance(value, str):
            raise ValueError(f"Vocabulary {kind} {path} is missing.")
        return value

    def _vocabulary_path(self, path: str) -> Any:
        value = _lookup(self._vocabulary, path)
        if value is _MISSING:
            raise ValueError(f"Vocabulary is missing {path}.")
        return value

    @staticmethod
    def _entry_value(entry: Mapping[str, Any], key: str, path: str) -> Any:
        if key not in entry:
            raise ValueError(f"Vocabulary {path} has an entry without {key}.")
        return entry[key]

    def _policy_path(self, path: str) -> Any:
        value = _lookup(self._policy, path)
        if value is _MISSING:
            raise ValueError(f"Governance policy is missing {path}.")
        return value

    def _policy_entries(self, path: str) -> tuple[Mapping[str, Any], ...]:
        entries = self._policy_path(path)
        if not isinstance(entries, tuple) or not all(isinstance(entry, Mapping) for entry in entries):
            raise ValueError(f"Governance policy {path} must be a list of objects.")
        return entries

    def _policy_number(self, path: str) -> Any:
        value = self._policy_path(path)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Governance policy {path} must be a number.")
        return value

    def _label_values(self, group: str) -> tuple[str, ...]:
        labels = _lookup(self._vocabulary, f"labels.{group}")
        return tuple(labels.values()) if isinstance(labels, Mapping) else ()

    def _require_label_key(self, group: str, key: Any, source: str) -> None:
        if _lookup(self._vocabulary, f"labels.{group}.{key}") is _MISSING:
            raise ValueError(f"{source} references {group}.{key}, which is not defined in vocabulary labels.")

    def _validate_policy(self) -> None:
        column_entries = self._policy_entries("sharePointColumns")
        column_names = _unique(_names(column_entries, "sharePointColumns"), "sharePointColumns column")
        self._columns = dict(zip(column_names, column_entries))

        index_entries = self._policy_entries("searchIndexFields")
        self._index_fields = _unique(_names(index_entries, "searchIndexFields"), "searchIndexFields field")

        projection = self._policy_entries("searchProjection")
        projected_fields = _unique(_names(projection, "searchProjection"), "searchProjection field")
        for entry in projection:
            field_name, column = entry["name"], entry.get("column")
            if column not in self._columns:
                raise ValueError(
                    f"searchProjection field {field_name} references column {column}, "
                    "which is missing from sharePointColumns."
                )
            if column in self._field_by_column:
                raise ValueError(f"searchProjection maps column {column} to more than one field.")
            self._projection[field_name] = column
            self._field_by_column[column] = field_name
        for field_name in projected_fields:
            if field_name not in self._index_fields:
                raise ValueError(f"searchProjection field {field_name} is missing from searchIndexFields.")
        for field_name in self._index_fields:
            if field_name not in self._projection:
                raise ValueError(f"searchIndexFields field {field_name} has no searchProjection entry.")
        for field_name in self._policy_path("knowledgeSourceDataFields"):
            if field_name not in self._index_fields:
                raise ValueError(f"knowledgeSourceDataFields field {field_name} is missing from searchIndexFields.")
        for column in self._policy_path("publishRequirements.requiredWhenPublished"):
            if column not in self._columns:
                raise ValueError(
                    f"publishRequirements.requiredWhenPublished references column {column}, "
                    "which is missing from sharePointColumns."
                )
        self._validate_eligibility()
        self._validate_similarity()
        self._validate_trust()

    def _validate_eligibility(self) -> None:
        self._policy_path("eligibility.lifecycleStatus")
        if not isinstance(self._policy_path("eligibility.authoritative"), bool):
            raise ValueError("eligibility.authoritative must be true or false.")
        if not self._policy_path("eligibility.trustedSensitivity"):
            raise ValueError("eligibility.trustedSensitivity must list at least one sensitivity label.")
        self._policy_path("eligibility.approvedSourceSystems")

    def _validate_similarity(self) -> None:
        near = self._policy_number("similarity.nearDuplicateCosine")
        conflict = self._policy_number("similarity.conflictCandidateCosine")
        if conflict > near:
            raise ValueError(
                f"similarity.conflictCandidateCosine ({conflict}) must not exceed "
                f"similarity.nearDuplicateCosine ({near})."
            )
        limit = self._policy_path("similarity.embeddingCharacterLimit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("similarity.embeddingCharacterLimit must be a positive whole number.")
        algorithm = self._policy_path("similarity.hashAlgorithm")
        try:
            hashlib.new(algorithm)
        except (TypeError, ValueError) as error:
            raise ValueError(f"similarity.hashAlgorithm {algorithm} is not supported by hashlib.") from error
        self._number_pattern = _compile(self._policy_path("similarity.numberPattern"), "similarity.numberPattern")
        self._whitespace_pattern = _compile(
            self._policy_path("similarity.whitespacePattern"), "similarity.whitespacePattern"
        )

    def _validate_trust(self) -> None:
        low = self._policy_number("trustScore.minScore")
        high = self._policy_number("trustScore.maxScore")
        if low > high:
            raise ValueError(f"trustScore.minScore ({low}) must not exceed trustScore.maxScore ({high}).")
        if tuple(self._policy_path("trustScore.range")) != (low, high):
            raise ValueError(f"trustScore.range must equal [minScore, maxScore], which is [{low}, {high}].")
        for section in ("weights", "penalties"):
            for key in self._policy_path(f"trustScore.{section}"):
                self._policy_number(f"trustScore.{section}.{key}")

    def _validate_vocabulary(self) -> None:
        for key, column in self._vocabulary_path("columns").items():
            if not isinstance(column, str) or not column:
                raise ValueError(f"Vocabulary column columns.{key} must name a SharePoint column.")
        for key, field_name in self._vocabulary_path("indexFields").items():
            if field_name not in self._index_fields:
                raise ValueError(
                    f"Vocabulary index field indexFields.{key} references {field_name}, "
                    "which is missing from searchIndexFields."
                )
            if self._projection[field_name] != self.column(key):
                raise ValueError(
                    f"Vocabulary index field indexFields.{key} is {field_name}, which searchProjection maps "
                    f"to {self._projection[field_name]}, but columns.{key} is {self.column(key)}."
                )
        self._validate_references()
        self._validate_label_choices()
        for group, keys in REQUIRED_LABELS.items():
            for key in keys:
                self._vocabulary_text(f"labels.{group}.{key}", "label")
        self._validate_messages()
        self._validate_hygiene_shape()
        self._validate_retrieval_shape()

    def _validate_references(self) -> None:
        authoritative_key = self._vocabulary_path("rules.authoritativeClaimLifecycleKey")
        self._require_label_key("lifecycleStatus", authoritative_key, "rules.authoritativeClaimLifecycleKey")
        for key in self._vocabulary_path("rules.staleLifecycleKeys"):
            self._require_label_key("lifecycleStatus", key, "rules.staleLifecycleKeys")
        for finding in self._vocabulary_path("hygiene.findings"):
            finding_id, rule = finding.get("id"), finding.get("rule")
            if rule not in FINDING_RULES:
                raise ValueError(f"hygiene.findings {finding_id} uses unknown rule {rule}.")
            group, value = FINDING_RULES[rule], finding.get("value")
            if group is None:
                if value is not None:
                    raise ValueError(f"hygiene.findings {finding_id} rule {rule} takes no value.")
                continue
            if value is None:
                raise ValueError(f"hygiene.findings {finding_id} rule {rule} needs a value.")
            self._require_label_key(group, value, f"hygiene.findings {finding_id}")
        lifecycle = self._policy_path("eligibility.lifecycleStatus")
        if lifecycle not in self._label_values("lifecycleStatus"):
            raise ValueError(f"eligibility.lifecycleStatus {lifecycle} is not a lifecycleStatus label.")
        for sensitivity in self._policy_path("eligibility.trustedSensitivity"):
            if sensitivity not in self._label_values("sensitivity"):
                raise ValueError(
                    f"eligibility.trustedSensitivity references {sensitivity}, which is not a sensitivity label."
                )
        for key in CLASSIFICATION_KEYS:
            default = self._vocabulary_path(f"classification.{key}.default")
            choices = self.choices(key)
            if default not in choices:
                raise ValueError(f"classification.{key}.default {default} is not a choice of {self.column(key)}.")
            for rule in self._vocabulary_path(f"classification.{key}.rules"):
                keyword = self._entry_value(rule, "keyword", f"classification.{key}.rules")
                value = self._entry_value(rule, "value", f"classification.{key}.rules")
                if value not in choices:
                    raise ValueError(
                        f"classification.{key} rule {keyword} references {value}, "
                        f"which is not a choice of {self.column(key)}."
                    )
        lifecycle_default = self._vocabulary_path("classification.suggestionDefaults.lifecycleStatus")
        if lifecycle_default not in self.choices("lifecycleStatus"):
            raise ValueError(
                f"classification.suggestionDefaults.lifecycleStatus {lifecycle_default} "
                "is not a choice of LifecycleStatus."
            )
        if not isinstance(self._vocabulary_path("classification.suggestionDefaults.authoritative"), bool):
            raise ValueError("classification.suggestionDefaults.authoritative must be true or false.")
        if not isinstance(self._vocabulary_path("classification.productFamilyMatchesChoices"), bool):
            raise ValueError("classification.productFamilyMatchesChoices must be true or false.")

    def _validate_label_choices(self) -> None:
        for group in CHOICE_LABEL_GROUPS:
            choices = self.choices(group)
            for key, value in self._vocabulary_path(f"labels.{group}").items():
                if value not in choices:
                    raise ValueError(
                        f"Vocabulary label labels.{group}.{key} is {value}, which is not a choice of "
                        f"{self.column(group)} in sharePointColumns."
                    )

    def _validate_messages(self) -> None:
        for group, keys in REQUIRED_MESSAGES.items():
            for key in keys:
                self._vocabulary_text(f"messages.{group}.{key}", "message")
        for section in ("weights", "penalties"):
            for key in self._policy_path(f"trustScore.{section}"):
                if not isinstance(_lookup(self._vocabulary, f"messages.trustReasons.{key}"), str):
                    raise ValueError(f"trustScore.{section}.{key} has no messages.trustReasons.{key} template.")

    def _validate_hygiene_shape(self) -> None:
        metrics = self._vocabulary_path("hygiene.metrics")
        for metric in metrics:
            if not isinstance(metric.get("key"), str):
                raise ValueError("hygiene.metrics has an entry without a key.")
            if not isinstance(metric.get("label"), str):
                raise ValueError(f"hygiene.metrics {metric.get('key')} has no label.")
        _unique([metric["key"] for metric in metrics], "hygiene.metrics key")
        findings = self._vocabulary_path("hygiene.findings")
        for finding in findings:
            for field_name in ("id", "title", "severity", "rule"):
                if not isinstance(finding.get(field_name), str):
                    raise ValueError(f"hygiene.findings entry {finding.get('id')} has no {field_name}.")
        _unique([finding["id"] for finding in findings], "hygiene.findings id")

    def _validate_retrieval_shape(self) -> None:
        for group, keys in REQUIRED_RETRIEVAL.items():
            for key in keys:
                if _lookup(self._vocabulary, f"retrieval.{group}.{key}") is _MISSING:
                    raise ValueError(f"Vocabulary retrieval entry retrieval.{group}.{key} is missing.")
        if not isinstance(self._vocabulary_path("retrieval.routing.governanceKeywords"), tuple):
            raise ValueError("retrieval.routing.governanceKeywords must be a list of keywords.")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _lookup(root: Any, path: str) -> Any:
    node = root
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _names(entries: tuple[Mapping[str, Any], ...], section: str) -> list[str]:
    names = []
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{section} has an entry without a name.")
        names.append(name)
    return names


def _unique(names: list[Any], label: str) -> list[Any]:
    seen: set[Any] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"Duplicate {label} {name}.")
        seen.add(name)
    return names


def _compile(pattern: Any, path: str) -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise ValueError(f"{path} must be a regular expression string.")
    try:
        return re.compile(pattern)
    except re.error as error:
        raise ValueError(f"{path} is not a valid regular expression: {error}.") from error
