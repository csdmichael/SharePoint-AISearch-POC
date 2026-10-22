"""Typed view over the shared governance vocabulary and policy files.

The code refers to logical keys only. Column names, labels, hygiene findings and thresholds are read
from config\\governance-vocabulary.json and config\\governance-policy.json, never copied into code.
"""

from __future__ import annotations

from typing import Any, Mapping


class GovernanceDefinitionError(ValueError):
    pass


REQUIRED_COLUMNS: tuple[str, ...] = (
    "title",
    "fileName",
    "artifactId",
    "knowledgeCategory",
    "sourceSystem",
    "knowledgeOwner",
    "ownerDisplayName",
    "lifecycleStatus",
    "authoritative",
    "reviewDate",
    "expirationDate",
    "effectiveDate",
    "documentType",
    "productFamily",
    "processArea",
    "sensitivity",
    "supersedesDocument",
    "businessUnit",
    "aiReady",
    "trustScore",
    "dataQualityStatus",
    "conflictStatus",
    "conflictWith",
    "duplicateOf",
    "contentHash",
    "trustReasons",
    "lastValidatedDate",
)

REQUIRED_LABEL_GROUPS: dict[str, tuple[str, ...]] = {
    "lifecycleStatus": ("draft", "published", "superseded", "archived"),
    "dataQualityStatus": ("good", "needsReview", "stale", "duplicate", "conflicting"),
    "conflictStatus": ("none", "conflictingAuthoritative", "conflictsWithAuthoritative"),
    "duplicateKind": ("exact", "near"),
}

KNOWN_FINDING_RULES: frozenset[str] = frozenset(
    {"conflictStatus", "duplicateKind", "expired", "missingOwner", "lifecycleStatus", "dataQualityNot"}
)

REQUIRED_MESSAGE_PATHS: tuple[tuple[str, ...], ...] = (
    ("duplicate", "exact"),
    ("duplicate", "near"),
    ("conflict", "candidate"),
)

REQUIRED_POLICY_PATHS: tuple[tuple[str, ...], ...] = (
    ("eligibility", "lifecycleStatus"),
    ("eligibility", "authoritative"),
    ("eligibility", "approvedSourceSystems"),
    ("similarity", "nearDuplicateCosine"),
    ("similarity", "conflictCandidateCosine"),
    ("similarity", "embeddingCharacterLimit"),
    ("similarity", "hashAlgorithm"),
    ("similarity", "numberPattern"),
    ("similarity", "whitespacePattern"),
    ("trustScore", "weights"),
    ("trustScore", "penalties"),
)


def _get_path(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for segment in path:
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


class Governance:
    """Validated accessor for the shared vocabulary and policy."""

    def __init__(self, vocabulary: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
        self.vocabulary: dict[str, Any] = dict(vocabulary)
        self.policy: dict[str, Any] = dict(policy)
        self._validate()

    def _validate(self) -> None:
        columns = self.vocabulary.get("columns")
        if not isinstance(columns, Mapping):
            raise GovernanceDefinitionError("governance-vocabulary.json: 'columns' section is missing")
        missing = [key for key in REQUIRED_COLUMNS if key not in columns]
        if missing:
            raise GovernanceDefinitionError(f"governance-vocabulary.json: columns is missing {', '.join(missing)}")
        labels = self.vocabulary.get("labels")
        if not isinstance(labels, Mapping):
            raise GovernanceDefinitionError("governance-vocabulary.json: 'labels' section is missing")
        for group, keys in REQUIRED_LABEL_GROUPS.items():
            if group not in labels:
                raise GovernanceDefinitionError(f"governance-vocabulary.json: labels.{group} is missing")
            absent = [key for key in keys if key not in labels[group]]
            if absent:
                raise GovernanceDefinitionError(
                    f"governance-vocabulary.json: labels.{group} is missing {', '.join(absent)}"
                )
        findings = _get_path(self.vocabulary, ("hygiene", "findings"))
        if not isinstance(findings, list) or not findings:
            raise GovernanceDefinitionError("governance-vocabulary.json: hygiene.findings must be a non-empty list")
        for finding in findings:
            if finding.get("rule") not in KNOWN_FINDING_RULES:
                raise GovernanceDefinitionError(
                    f"governance-vocabulary.json: finding '{finding.get('id')}' uses unknown rule "
                    f"'{finding.get('rule')}'"
                )
        if not isinstance(_get_path(self.vocabulary, ("hygiene", "metrics")), list):
            raise GovernanceDefinitionError("governance-vocabulary.json: hygiene.metrics is missing")
        missing_messages = [".".join(path) for path in REQUIRED_MESSAGE_PATHS
                            if not isinstance(_get_path(self.vocabulary, ("messages",) + path), str)]
        if missing_messages:
            raise GovernanceDefinitionError(f"governance-vocabulary.json: messages.{', messages.'.join(missing_messages)} is missing")
        missing_policy = [".".join(path) for path in REQUIRED_POLICY_PATHS if _get_path(self.policy, path) is None]
        if missing_policy:
            raise GovernanceDefinitionError(f"governance-policy.json: missing {', '.join(missing_policy)}")

    def column(self, key: str) -> str:
        return str(self.vocabulary["columns"][key])

    def column_names(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.vocabulary["columns"].items()}

    def label(self, group: str, key: str) -> str:
        return str(self.vocabulary["labels"][group][key])

    def labels(self, group: str) -> dict[str, str]:
        return {str(k): str(v) for k, v in self.vocabulary["labels"][group].items()}

    def key_for_label(self, group: str, value: str | None) -> str | None:
        if value is None:
            return None
        wanted = normalize_token(value)
        for key, label in self.labels(group).items():
            if normalize_token(label) == wanted or normalize_token(key) == wanted:
                return key
        return None

    @property
    def metrics(self) -> list[dict[str, str]]:
        return [dict(item) for item in self.vocabulary["hygiene"]["metrics"]]

    @property
    def findings(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.vocabulary["hygiene"]["findings"]]

    @property
    def message_templates(self) -> dict[str, Any]:
        return dict(self.vocabulary.get("messages", {}))

    @property
    def authoritative_lifecycle_key(self) -> str:
        return str(self.vocabulary["rules"]["authoritativeClaimLifecycleKey"])

    @property
    def stale_lifecycle_keys(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.vocabulary["rules"]["staleLifecycleKeys"])

    @property
    def similarity(self) -> dict[str, Any]:
        return dict(self.policy["similarity"])

    @property
    def eligibility(self) -> dict[str, Any]:
        return dict(self.policy["eligibility"])

    @property
    def trust_weights(self) -> dict[str, int]:
        return dict(self.policy["trustScore"]["weights"])

    @property
    def trust_penalties(self) -> dict[str, int]:
        return dict(self.policy["trustScore"]["penalties"])


def normalize_token(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())
