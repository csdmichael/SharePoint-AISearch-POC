"""Initial governance values for a newly published artifact, computed with the policy the sync engine uses.

The same weights, blockers and eligibility rules come from config\\governance-policy.json and
config\\governance-vocabulary.json, so a published artifact starts with the AIReady and TrustScore the scheduled
governance sync would also assign. The sync remains the owner of these system-computed columns and recomputes them
(including duplicate and conflict detection) on its next run.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from app.core.governance import Governance

TRUST_REASON_SEPARATOR = "\n"
NORMALIZED_SEPARATOR = " "


@dataclass(frozen=True)
class GovernanceOutcome:
    lifecycle_status: str
    data_quality: str
    conflict_status: str
    ai_ready: bool
    blockers: tuple[str, ...]
    trust_score: int
    trust_reasons: tuple[str, ...]


def evaluate(
    governance: Governance,
    *,
    authoritative: bool,
    owner_present: bool,
    review_date: date,
    sensitivity: str,
    source_system: str,
    today: date,
) -> GovernanceOutcome:
    eligibility = governance.eligibility
    labels = governance.labels("lifecycleStatus")
    published_label = governance.label("lifecycleStatus", "published")
    trusted_sensitivity = eligibility.get("trustedSensitivity", [])
    approved_source = source_system in eligibility.get("approvedSourceSystems", [])
    review_current = review_date >= today
    messages = governance.message_templates
    blocker_text = messages.get("blockers", {})
    reason_text = messages.get("trustReasons", {})

    blockers: list[str] = []
    if published_label != eligibility["lifecycleStatus"]:
        blockers.append(blocker_text["lifecycleNotRequired"].format(value=published_label))
    if authoritative != eligibility["authoritative"]:
        blockers.append(blocker_text["notAuthoritative"])
    if not owner_present:
        blockers.append(blocker_text["ownerMissing"])
    if not review_current:
        blockers.append(blocker_text["reviewPassed"].format(value=review_date.isoformat()))
    if trusted_sensitivity and sensitivity not in trusted_sensitivity:
        blockers.append(blocker_text["sensitivityNotTrusted"].format(value=sensitivity))
    if not approved_source:
        blockers.append(blocker_text["sourceNotApproved"])

    data_quality_labels = governance.labels("dataQualityStatus")
    needs_review = not authoritative or not owner_present
    if not review_current:
        data_quality = data_quality_labels["stale"]
    elif needs_review:
        data_quality = data_quality_labels["needsReview"]
    else:
        data_quality = data_quality_labels["good"]

    facts = {
        "authoritative": authoritative,
        "published": True,
        "reviewCurrent": review_current,
        "ownerPresent": owner_present,
        "dataQualityGood": data_quality == data_quality_labels["good"],
        "notDuplicate": True,
        "approvedSource": approved_source,
    }
    components = [
        (points, reason_text[key].format(reviewDate=review_date.isoformat()))
        for key, points in governance.trust_weights.items() if facts.get(key, False)
    ]
    bounds = governance.policy["trustScore"].get("range") or [
        governance.policy["trustScore"]["minScore"], governance.policy["trustScore"]["maxScore"]
    ]
    score = min(bounds[1], max(bounds[0], sum(points for points, _ in components)))
    reasons = [f"{points:+g} {text}" for points, text in components]
    reasons.append(reason_text["total"].format(score=score))
    return GovernanceOutcome(
        lifecycle_status=labels["published"],
        data_quality=data_quality,
        conflict_status=governance.label("conflictStatus", "none"),
        ai_ready=not blockers,
        blockers=tuple(blockers),
        trust_score=int(score),
        trust_reasons=tuple(reasons),
    )


def content_hash(governance: Governance, text: str) -> str:
    """SHA-256 (the policy's algorithm) of whitespace-normalized text, like the governance sync's ContentHash."""

    similarity = governance.similarity
    normalized = re.sub(similarity["whitespacePattern"], NORMALIZED_SEPARATOR, text).strip()
    return hashlib.new(similarity["hashAlgorithm"], normalized.encode("utf-8")).hexdigest()


def classify(governance: Governance, key: str, text: str) -> str:
    """Keyword classification from the vocabulary (documentType, processArea, sensitivity), default when no rule hits."""

    block = governance.classification(key)
    lowered = text.lower()
    for rule in block.get("rules", []):
        if str(rule["keyword"]).lower() in lowered:
            return str(rule["value"])
    return str(block.get("default", ""))
