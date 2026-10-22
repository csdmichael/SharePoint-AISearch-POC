"""Governance evaluation for the Trusted Knowledge track.

Computes duplicate clusters, conflicts, data quality, explainable trust, AI readiness and the
SharePoint and search fields that carry them. Status labels and reason text come from the Policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from . import similarity
from .policy import Policy
from .similarity import CONFLICT, EXACT, NEAR, PairFinding, Signal, classify_pairs

# Logical keys of the statuses that are stored internally. Display labels come from the vocabulary.
DATA_QUALITY_GOOD = "good"
DATA_QUALITY_NEEDS_REVIEW = "needsReview"
DATA_QUALITY_STALE = "stale"
DATA_QUALITY_DUPLICATE = "duplicate"
DATA_QUALITY_CONFLICTING = "conflicting"
CONFLICT_NONE = "none"
CONFLICT_AUTHORITATIVE = "conflictingAuthoritative"
CONFLICTS_WITH_AUTHORITATIVE = "conflictsWithAuthoritative"
PUBLISHED = "published"
DRAFT = "draft"
SUPERSEDED = "superseded"
ARCHIVED = "archived"
DUPLICATE_KINDS = (EXACT, NEAR)
# Presentation and serialization details of computed fields. They are not policy values.
SIMILARITY_FORMAT = "g"
CONFLICT_WITH_SEPARATOR = "; "
TRUST_REASON_SEPARATOR = "\n"
EMPTY_TEXT = ""


def parse_date(value: Any) -> date | None:
    if value is None or value == EMPTY_TEXT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


@dataclass(frozen=True)
class Declared:
    """SharePoint metadata of one document. Lifecycle, sensitivity and dates keep their SharePoint values."""

    key: str
    artifact_id: str
    title: str
    category: str
    source_system: str
    knowledge_owner: str | None
    lifecycle_status: str
    authoritative: bool
    authoritative_claim: bool
    review_date: date | None
    document_type: str
    product_family: str
    process_area: str
    sensitivity: str
    effective_date: date | None
    expiration_date: date | None
    supersedes_document: str | None
    values: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def scope(self) -> tuple[str, str, str]:
        return (self.product_family, self.process_area, self.document_type)

    @classmethod
    def from_manifest(cls, entry: Mapping[str, Any], policy: Policy) -> Declared:
        declared = entry["declared"]

        def read(key: str) -> Any:
            return declared.get(policy.column(key))

        def require(key: str) -> Any:
            value = read(key)
            if value is None or value == EMPTY_TEXT:
                raise ValueError(f"Manifest entry is missing {policy.column(key)}.")
            return value

        lifecycle = require("lifecycleStatus")
        authoritative = bool(require("authoritative"))
        return cls(
            key=require("fileName"),
            artifact_id=require("artifactId"),
            title=require("title"),
            category=require("knowledgeCategory"),
            source_system=require("sourceSystem"),
            knowledge_owner=read("knowledgeOwner") or None,
            lifecycle_status=lifecycle,
            authoritative=authoritative,
            authoritative_claim=lifecycle == policy.authoritative_claim_label() and authoritative,
            review_date=parse_date(read("reviewDate")),
            document_type=require("documentType"),
            product_family=require("productFamily"),
            process_area=require("processArea"),
            sensitivity=require("sensitivity"),
            effective_date=parse_date(read("effectiveDate")),
            expiration_date=parse_date(read("expirationDate")),
            supersedes_document=read("supersedesDocument") or None,
            values=dict(declared),
        )


@dataclass(frozen=True)
class Measurement:
    content_hash: str
    numeric_signature: tuple[str, ...]
    vector: tuple[float, ...]

    @classmethod
    def from_manifest(cls, entry: Mapping[str, Any], policy: Policy) -> Measurement:
        normalized = similarity.normalize_text(entry["body"], policy.whitespace_pattern())
        return cls(
            content_hash=similarity.content_hash(normalized, policy.hash_algorithm()),
            numeric_signature=similarity.numeric_signature(normalized, policy.number_pattern()),
            vector=tuple(float(value) for value in entry["vector"]),
        )


@dataclass
class Assessment:
    """Computed governance state of one document. Status fields hold logical keys, not labels."""

    declared: Declared
    measurement: Measurement
    duplicate_of: str | None = None
    duplicate_kind: str | None = None
    conflict: str = CONFLICT_NONE
    conflict_with: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    owner_present: bool = False
    review_current: bool = False
    review_overdue: bool = False
    expired: bool = False
    publish_gaps: list[str] = field(default_factory=list)
    data_quality: str | None = None
    trust_score: int = 0
    trust_reasons: list[str] = field(default_factory=list)
    ai_ready: bool = False
    ai_ready_blockers: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.declared.key

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None


@dataclass
class Evaluation:
    as_of: date
    assessments: list[Assessment]
    pair_findings: list[PairFinding]

    def by_key(self) -> dict[str, Assessment]:
        return {assessment.key: assessment for assessment in self.assessments}


def evaluate(
    declarations: Sequence[Declared],
    measurements: Mapping[str, Measurement],
    policy: Policy,
    as_of: date,
) -> Evaluation:
    assessments: dict[str, Assessment] = {}
    for declared in declarations:
        if declared.key in assessments:
            raise ValueError(f"Duplicate document {declared.key}.")
        if declared.key not in measurements:
            raise ValueError(f"No measurement for document {declared.key}.")
        assessments[declared.key] = Assessment(declared=declared, measurement=measurements[declared.key])
    artifact_ids: set[str] = set()
    for assessment in assessments.values():
        artifact_id = assessment.declared.artifact_id
        if artifact_id in artifact_ids:
            raise ValueError(f"Duplicate {policy.column('artifactId')} {artifact_id}.")
        artifact_ids.add(artifact_id)
    signals = [
        Signal(
            key=item.declared.key,
            content_hash=item.measurement.content_hash,
            numeric_signature=item.measurement.numeric_signature,
            scope=item.declared.scope,
            authoritative_claim=item.declared.authoritative_claim,
            supersedes=item.declared.supersedes_document,
            vector=item.measurement.vector,
        )
        for item in assessments.values()
    ]
    findings = classify_pairs(
        signals,
        policy.near_duplicate_cosine(),
        policy.conflict_candidate_cosine(),
    )
    _assign_duplicates(assessments, findings, policy)
    _assign_conflicts(assessments, findings, policy)
    for assessment in assessments.values():
        _assess(assessment, policy, as_of)
    return Evaluation(as_of=as_of, assessments=list(assessments.values()), pair_findings=findings)


def _assign_duplicates(assessments: Mapping[str, Assessment], findings: Sequence[PairFinding], policy: Policy) -> None:
    """Groups exact and near pairs into clusters and gives each non-canonical member one canonical."""
    duplicate_pairs = {frozenset((f.first, f.second)): f for f in findings if f.kind in DUPLICATE_KINDS}
    parent = {key: key for key in assessments}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for pair in duplicate_pairs.values():
        parent[root(pair.second)] = root(pair.first)
    clusters: dict[str, list[str]] = {}
    for key in assessments:
        clusters.setdefault(root(key), []).append(key)
    for members in clusters.values():
        if len(members) < 2:
            continue
        canonical_key = min(members, key=lambda key: _canonical_rank(assessments[key]))
        for key in members:
            if key == canonical_key:
                continue
            member = assessments[key]
            pair = duplicate_pairs.get(frozenset((key, canonical_key)))
            member.duplicate_of = canonical_key
            # Members without a direct pair to the canonical are linked through near-duplicate chains.
            member.duplicate_kind = pair.kind if pair is not None else NEAR
            if pair is not None:
                member.evidence.append(_pair_evidence(pair, policy))


def _canonical_rank(assessment: Assessment) -> tuple[int, int, int, str]:
    """Authoritative claims first, then the newest EffectiveDate, then the lowest ArtifactId."""
    declared = assessment.declared
    effective = declared.effective_date
    return (
        0 if declared.authoritative_claim else 1,
        0 if effective is not None else 1,
        -effective.toordinal() if effective is not None else 0,
        declared.artifact_id,
    )


def _assign_conflicts(assessments: Mapping[str, Assessment], findings: Sequence[PairFinding], policy: Policy) -> None:
    for finding in findings:
        if finding.kind != CONFLICT:
            continue
        first = assessments[finding.first]
        second = assessments[finding.second]
        first.conflict_with.append(second.key)
        second.conflict_with.append(first.key)
        evidence = _pair_evidence(finding, policy)
        first.evidence.append(evidence)
        second.evidence.append(evidence)
        first_claim = first.declared.authoritative_claim
        second_claim = second.declared.authoritative_claim
        if first_claim and second_claim:
            first.conflict = second.conflict = CONFLICT_AUTHORITATIVE
        elif first_claim:
            second.conflict = CONFLICTS_WITH_AUTHORITATIVE
        elif second_claim:
            first.conflict = CONFLICTS_WITH_AUTHORITATIVE
    for assessment in assessments.values():
        assessment.conflict_with.sort()


def _pair_evidence(finding: PairFinding, policy: Policy) -> str:
    if finding.kind == EXACT:
        return policy.message("duplicate", "exact")
    similarity_text = format(finding.similarity, SIMILARITY_FORMAT)
    if finding.kind == NEAR:
        return policy.render(policy.message("duplicate", "near"), similarity=similarity_text)
    return policy.render(policy.message("conflict", "candidate"), similarity=similarity_text)


def _assess(assessment: Assessment, policy: Policy, as_of: date) -> None:
    declared = assessment.declared
    assessment.owner_present = bool(declared.knowledge_owner)
    assessment.review_current = declared.review_date is not None and declared.review_date >= as_of
    assessment.review_overdue = declared.review_date is not None and declared.review_date < as_of
    assessment.expired = declared.expiration_date is not None and declared.expiration_date < as_of
    is_published = _lifecycle_is(declared, policy, PUBLISHED)
    approved_source = declared.source_system in policy.approved_source_systems()
    assessment.publish_gaps = (
        [column for column in policy.required_when_published() if declared.values.get(column) in (None, EMPTY_TEXT)]
        if is_published else []
    )
    assessment.data_quality = _data_quality(assessment, policy, is_published)
    _score(assessment, policy, is_published, approved_source)
    _eligibility(assessment, policy, as_of, approved_source)


def _data_quality(assessment: Assessment, policy: Policy, is_published: bool) -> str:
    declared = assessment.declared
    if assessment.conflict == CONFLICT_AUTHORITATIVE:
        return DATA_QUALITY_CONFLICTING
    if assessment.is_duplicate:
        return DATA_QUALITY_DUPLICATE
    if declared.lifecycle_status in policy.stale_lifecycle_labels() or assessment.expired or assessment.review_overdue:
        return DATA_QUALITY_STALE
    needs_review = (
        not is_published
        or not declared.authoritative
        or bool(assessment.publish_gaps)
        or assessment.conflict == CONFLICTS_WITH_AUTHORITATIVE
    )
    return DATA_QUALITY_NEEDS_REVIEW if needs_review else DATA_QUALITY_GOOD


def _score(assessment: Assessment, policy: Policy, is_published: bool, approved_source: bool) -> None:
    declared = assessment.declared
    facts = {
        "authoritative": declared.authoritative,
        "published": is_published,
        "reviewCurrent": assessment.review_current,
        "ownerPresent": assessment.owner_present,
        "dataQualityGood": assessment.data_quality == DATA_QUALITY_GOOD,
        "notDuplicate": not assessment.is_duplicate,
        "approvedSource": approved_source,
        "draft": _lifecycle_is(declared, policy, DRAFT),
        "superseded": _lifecycle_is(declared, policy, SUPERSEDED),
        "archived": _lifecycle_is(declared, policy, ARCHIVED),
        "expired": assessment.expired,
        "duplicate": assessment.is_duplicate,
        "missingOwner": not assessment.owner_present,
        "conflictingAuthoritative": assessment.conflict == CONFLICT_AUTHORITATIVE,
        "conflictsWithAuthoritative": assessment.conflict == CONFLICTS_WITH_AUTHORITATIVE,
    }
    placeholders = {
        "reviewDate": _iso(declared.review_date),
        "expirationDate": _iso(declared.expiration_date),
        "canonical": assessment.duplicate_of or EMPTY_TEXT,
    }
    components = [
        (points, _reason(policy, key, placeholders))
        for key, points in policy.trust_weights().items() if _fact(facts, key)
    ]
    components += [
        (-points, _reason(policy, key, placeholders))
        for key, points in policy.trust_penalties().items() if _fact(facts, key)
    ]
    low, high = policy.trust_bounds()
    total = sum(points for points, _ in components)
    assessment.trust_score = min(high, max(low, total))
    assessment.trust_reasons = [f"{points:+g} {text}" for points, text in components]
    assessment.trust_reasons.append(
        policy.render(policy.message("trustReasons", "total"), score=assessment.trust_score)
    )


def _eligibility(assessment: Assessment, policy: Policy, as_of: date, approved_source: bool) -> None:
    declared = assessment.declared
    blockers: list[str] = []

    def block(key: str, **values: Any) -> None:
        blockers.append(policy.render(policy.message("blockers", key), **values))

    if declared.lifecycle_status != policy.required_lifecycle():
        block("lifecycleNotRequired", value=declared.lifecycle_status)
    if declared.authoritative != policy.required_authoritative():
        block("notAuthoritative")
    if not assessment.owner_present:
        block("ownerMissing")
    if declared.review_date is None:
        block("reviewMissing")
    elif assessment.review_overdue:
        block("reviewPassed", value=declared.review_date.isoformat())
    if assessment.expired:
        block("expirationPassed", value=declared.expiration_date.isoformat())
    if declared.effective_date is not None and declared.effective_date > as_of:
        block("effectiveInFuture", value=declared.effective_date.isoformat())
    if assessment.is_duplicate:
        block("duplicateOf", value=assessment.duplicate_of)
    if declared.sensitivity not in policy.trusted_sensitivity():
        block("sensitivityNotTrusted", value=declared.sensitivity)
    if not approved_source:
        block("sourceNotApproved")
    assessment.ai_ready_blockers = blockers
    assessment.ai_ready = not blockers


def _lifecycle_is(declared: Declared, policy: Policy, key: str) -> bool:
    return declared.lifecycle_status == policy.label("lifecycleStatus", key)


def _fact(facts: Mapping[str, bool], key: str) -> bool:
    if key not in facts:
        raise ValueError(f"Trust component {key} has no governance fact.")
    return facts[key]


def _reason(policy: Policy, key: str, placeholders: Mapping[str, str]) -> str:
    return policy.render(policy.message("trustReasons", key), **placeholders)


def _iso(value: date | None) -> str:
    return value.isoformat() if value is not None else EMPTY_TEXT


def computed_sharepoint_fields(
    assessment: Assessment,
    as_of: date,
    owner_display_name: str | None,
    policy: Policy,
) -> dict[str, Any]:
    """Values for the system-computed SharePoint columns, keyed by SharePoint column name."""
    fields: dict[str, Any] = {
        policy.column("aiReady"): assessment.ai_ready,
        policy.column("trustScore"): assessment.trust_score,
        policy.column("dataQualityStatus"): policy.label("dataQualityStatus", assessment.data_quality),
        policy.column("conflictStatus"): policy.label("conflictStatus", assessment.conflict),
        policy.column("conflictWith"): CONFLICT_WITH_SEPARATOR.join(assessment.conflict_with),
        policy.column("duplicateOf"): assessment.duplicate_of or EMPTY_TEXT,
        policy.column("contentHash"): assessment.measurement.content_hash,
        policy.column("trustReasons"): TRUST_REASON_SEPARATOR.join(assessment.trust_reasons),
        policy.column("lastValidatedDate"): as_of.isoformat(),
    }
    if owner_display_name and assessment.declared.knowledge_owner:
        fields[policy.column("ownerDisplayName")] = owner_display_name
    return fields


def project_to_search(fields: Mapping[str, Any], policy: Policy) -> dict[str, Any]:
    """Maps SharePoint column values to search index fields through searchProjection."""
    return {field_name: fields.get(column) for field_name, column in policy.search_projection()}


def suggest_metadata(
    normalized_text: str,
    title: str,
    policy: Policy,
    product_family_choices: Sequence[str],
) -> dict[str, Any]:
    """Suggested SharePoint values for a new document. Keys are SharePoint column names.

    The owner-review flag is a workflow setting exposed by Policy.requires_owner_review(), not a column.
    """
    lowered = f"{title} {normalized_text}".lower()
    defaults = policy.suggestion_defaults()
    return {
        policy.column("documentType"): _classify(lowered, policy, "documentType"),
        policy.column("processArea"): _classify(lowered, policy, "processArea"),
        policy.column("productFamily"): _match_product_family(lowered, product_family_choices, policy),
        policy.column("sensitivity"): _classify(lowered, policy, "sensitivity"),
        policy.column("lifecycleStatus"): defaults["lifecycleStatus"],
        policy.column("authoritative"): defaults["authoritative"],
        policy.column("knowledgeOwner"): None,
    }


def _classify(lowered: str, policy: Policy, key: str) -> str:
    for keyword, value in policy.classification_rules(key):
        if keyword.lower() in lowered:
            return value
    return policy.classification_default(key)


def _match_product_family(lowered: str, choices: Sequence[str], policy: Policy) -> str | None:
    if not policy.product_family_matches_choices():
        return None
    for choice in choices:
        if choice.lower() in lowered:
            return choice
    return None
