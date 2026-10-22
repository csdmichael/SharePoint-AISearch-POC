"""Trusted retrieval: question routing, deterministic OData filters, exclusion reasons and the answer card.

Search records are keyed by search index field names resolved through the Policy. Statuses, banners,
card titles, labels and filter templates come from the vocabulary's retrieval block.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from .governance import (
    CONFLICT_AUTHORITATIVE,
    CONFLICTS_WITH_AUTHORITATIVE,
    DATA_QUALITY_GOOD,
    parse_date,
)
from .policy import Policy

# Source-reference keys that the knowledge source preserves in every reference. The governance
# policy does not define them because they are not SharePoint columns or search index fields.
# Every other reference key is the search index field name that Policy.search_field returns.
SOURCE_TITLE_KEY = "title"
SOURCE_CITATION_KEY = "document_url"
SOURCE_WHY_TRUSTED_KEY = "why_trusted"
# OData string literals double embedded quotes. Booleans are written as lowercase OData keywords.
ODATA_QUOTE = "'"
ODATA_QUOTE_ESCAPE = "''"
ODATA_BOOLEAN = {True: "true", False: "false"}


def route_question(question: str, policy: Policy) -> str:
    routing = policy.retrieval_block()["routing"]
    lowered = question.lower()
    if any(keyword.lower() in lowered for keyword in routing["governanceKeywords"]):
        return routing["governanceTool"]
    return routing["trustedTool"]


def trusted_base_filter(policy: Policy) -> str:
    templates = policy.retrieval_block()["filterTemplates"]
    clauses = [
        templates["equalsText"].format(
            field=policy.index_field("lifecycleStatus"),
            value=_escape_text(policy.required_lifecycle()),
        ),
        templates["equalsBoolean"].format(
            field=policy.index_field("authoritative"),
            value=ODATA_BOOLEAN[policy.required_authoritative()],
        ),
        templates["equalsBoolean"].format(field=policy.index_field("aiReady"), value=ODATA_BOOLEAN[True]),
        _sensitivity_clause(policy),
    ]
    return templates["combine"].join(clauses)


def governance_base_filter(policy: Policy) -> str:
    return _sensitivity_clause(policy)


def _sensitivity_clause(policy: Policy) -> str:
    templates = policy.retrieval_block()["filterTemplates"]
    field_name = policy.index_field("sensitivity")
    clauses = [
        templates["equalsText"].format(field=field_name, value=_escape_text(value))
        for value in policy.trusted_sensitivity()
    ]
    if len(clauses) == 1:
        return clauses[0]
    return templates["group"].format(clauses=templates["anyOf"].join(clauses))


def _escape_text(value: str) -> str:
    return value.replace(ODATA_QUOTE, ODATA_QUOTE_ESCAPE)


def is_trusted(source: Mapping[str, Any], policy: Policy) -> bool:
    return (
        source.get(policy.search_field("lifecycleStatus")) == policy.required_lifecycle()
        and bool(source.get(policy.search_field("authoritative"))) == policy.required_authoritative()
        and bool(source.get(policy.search_field("aiReady")))
        and source.get(policy.search_field("sensitivity")) in policy.trusted_sensitivity()
    )


def exclusion_reasons(source: Mapping[str, Any], as_of: date, policy: Policy) -> list[str]:
    reasons: list[str] = []
    lifecycle = source.get(policy.search_field("lifecycleStatus"))
    if lifecycle != policy.required_lifecycle():
        reasons.append(policy.render(policy.message("exclusions", "lifecycle"), value=lifecycle))
    if not source.get(policy.search_field("authoritative")):
        reasons.append(policy.message("exclusions", "notAuthoritative"))
    duplicate_of = source.get(policy.search_field("duplicateOf"))
    if duplicate_of:
        reasons.append(policy.render(policy.message("exclusions", "duplicate"), value=duplicate_of))
    expiration = parse_date(source.get(policy.search_field("expirationDate")))
    if expiration is not None and expiration < as_of:
        reasons.append(policy.render(policy.message("exclusions", "expired"), value=expiration.isoformat()))
    review = parse_date(source.get(policy.search_field("reviewDate")))
    if review is not None and review < as_of:
        reasons.append(policy.render(policy.message("exclusions", "reviewPassed"), value=review.isoformat()))
    conflict_label = policy.label("conflictStatus", CONFLICTS_WITH_AUTHORITATIVE)
    if source.get(policy.search_field("conflictStatus")) == conflict_label:
        reasons.append(policy.message("exclusions", "conflictsWithAuthoritative"))
    if not reasons and not source.get(policy.search_field("aiReady")):
        reasons.append(policy.message("exclusions", "notAiReady"))
    return reasons


def build_trusted_card(sources: Sequence[Mapping[str, Any]], as_of: date, policy: Policy) -> dict[str, Any]:
    """Builds the answer card. Sources are in search rank order, and ties keep that order."""
    block = policy.retrieval_block()
    conflict_label = policy.label("conflictStatus", CONFLICT_AUTHORITATIVE)
    conflicting = [s for s in sources if s.get(policy.search_field("conflictStatus")) == conflict_label]
    trusted = [s for s in sources if is_trusted(s, policy)]
    excluded = [
        {SOURCE_TITLE_KEY: s.get(SOURCE_TITLE_KEY), "reasons": exclusion_reasons(s, as_of, policy)}
        for s in sources if not is_trusted(s, policy)
    ]
    selected: Mapping[str, Any] | None = None
    banner: str | None = None
    if conflicting:
        status = block["statuses"]["conflict"]
        banner = block["banners"]["conflict"]
    elif trusted:
        status = block["statuses"]["trusted"]
        selected = max(trusted, key=lambda s: _trust_score(s, policy))
    else:
        status = block["statuses"]["noSource"]
        banner = block["banners"]["noSource"]
    return {
        "status": status,
        "banner": banner,
        "selected": _card_source(selected, as_of, policy) if selected is not None else None,
        "conflicts": [_card_source(s, as_of, policy) for s in conflicting],
        "excluded": excluded,
    }


def _trust_score(source: Mapping[str, Any], policy: Policy) -> int:
    return int(source.get(policy.search_field("trustScore")) or 0)


def _card_source(source: Mapping[str, Any], as_of: date, policy: Policy) -> dict[str, Any]:
    review = parse_date(source.get(policy.search_field("reviewDate")))
    # Card keys are the configured search index field names, so the card matches the index.
    return {
        SOURCE_TITLE_KEY: source.get(SOURCE_TITLE_KEY),
        SOURCE_CITATION_KEY: source.get(SOURCE_CITATION_KEY),
        policy.search_field("lifecycleStatus"): source.get(policy.search_field("lifecycleStatus")),
        policy.search_field("authoritative"): bool(source.get(policy.search_field("authoritative"))),
        policy.search_field("ownerDisplayName"): source.get(policy.search_field("ownerDisplayName")),
        policy.search_field("reviewDate"): review.isoformat() if review is not None else None,
        policy.search_field("trustScore"): source.get(policy.search_field("trustScore")),
        policy.search_field("dataQualityStatus"): source.get(policy.search_field("dataQualityStatus")),
        SOURCE_WHY_TRUSTED_KEY: _why_trusted(source, as_of, policy),
    }


def _why_trusted(source: Mapping[str, Any], as_of: date, policy: Policy) -> str:
    tokens_text = policy.retrieval_block()["whyTrustedTokens"]
    tokens: list[str] = []
    if source.get(policy.search_field("lifecycleStatus")) == policy.required_lifecycle():
        tokens.append(tokens_text["published"])
    if source.get(policy.search_field("authoritative")):
        tokens.append(tokens_text["authoritative"])
    review = parse_date(source.get(policy.search_field("reviewDate")))
    if review is not None and review >= as_of:
        tokens.append(tokens_text["current"])
    if source.get(policy.search_field("ownerDisplayName")):
        tokens.append(tokens_text["owned"])
    if source.get(policy.search_field("dataQualityStatus")) == policy.label("dataQualityStatus", DATA_QUALITY_GOOD):
        tokens.append(tokens_text["validated"])
    return tokens_text["joiner"].join(tokens)


def render_card_markdown(card: Mapping[str, Any], policy: Policy) -> str:
    block = policy.retrieval_block()
    if card["status"] == block["statuses"]["conflict"]:
        lines = [f"**{block['cardTitles']['conflict']}**", "", card["banner"], ""]
        for source in card["conflicts"]:
            lines.append(_card_lines(source, policy))
            lines.append("")
        return "\n".join(lines).rstrip()
    if card["status"] == block["statuses"]["noSource"]:
        return f"**{card['banner']}**"
    return f"**{block['cardTitles']['trusted']}**\n" + _card_lines(card["selected"], policy)


def _card_lines(source: Mapping[str, Any], policy: Policy) -> str:
    labels = policy.retrieval_block()["cardLabels"]
    _, maximum = policy.trust_bounds()
    authoritative = labels["yes"] if source[policy.search_field("authoritative")] else labels["no"]
    lifecycle = source[policy.search_field("lifecycleStatus")]
    owner = source[policy.search_field("ownerDisplayName")]
    review = source[policy.search_field("reviewDate")]
    score = source[policy.search_field("trustScore")]
    lines = [
        f"{labels['source']}: {source[SOURCE_TITLE_KEY]}",
        f"{labels['status']}: {lifecycle}",
        f"{labels['authoritative']}: {authoritative}",
        f"{labels['knowledgeOwner']}: {owner or labels['missing']}",
        f"{labels['reviewDate']}: {review or labels['missing']}",
        f"{labels['trustScore']}: {score}/{maximum}",
        f"{labels['whyTrusted']}: {source[SOURCE_WHY_TRUSTED_KEY] or labels['notEligible']}",
        f"{labels['citation']}: {source[SOURCE_CITATION_KEY]}",
    ]
    return "\n".join(lines)
