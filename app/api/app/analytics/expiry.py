"""Expiry and review analysis from governance metadata and from date phrases found in document text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

from app.core.config import ExpiryConfig

DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y")
KIND_REVIEW = "review"
KIND_EXPIRATION = "expiration"
SOURCE_METADATA = "metadata"
SOURCE_TEXT = "text"


@dataclass(frozen=True)
class ExpiryDoc:
    key: str
    name: str
    title: str
    lifecycle: str | None
    metadata_expiration: date | None
    metadata_review: date | None
    text: str | None


@dataclass(frozen=True)
class TextDate:
    kind: str
    value: date
    snippet: str


@dataclass(frozen=True)
class ExpiryFinding:
    key: str
    expired: bool
    expired_by: tuple[str, ...]
    expiration_date: date | None
    days_past_expiration: int | None
    review_date: date | None
    review_overdue: bool
    overdue_by: tuple[str, ...]
    days_overdue: int | None
    text_dates: tuple[TextDate, ...]


def parse_loose_date(text: str) -> date | None:
    cleaned = re.sub(r"\s+", " ", text.replace(",", ", ")).replace(" ,", ",").strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def extract_text_dates(text: str, patterns: Iterable[re.Pattern[str]], max_chars: int) -> tuple[TextDate, ...]:
    window = text[:max_chars]
    found: list[TextDate] = []
    for pattern in patterns:
        for match in pattern.finditer(window):
            value = parse_loose_date(match.group("date"))
            if value is None:
                continue
            kind = KIND_REVIEW if "review" in match.group(0).lower() else KIND_EXPIRATION
            found.append(TextDate(kind=kind, value=value, snippet=match.group(0).strip()[:160]))
    found.sort(key=lambda item: (item.kind, item.value, item.snippet))
    return tuple(found)


def compile_date_patterns(config: ExpiryConfig) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in config.datePatterns]


def analyze_expiry(
    docs: Sequence[ExpiryDoc],
    *,
    as_of: date,
    config: ExpiryConfig,
) -> dict[str, ExpiryFinding]:
    patterns = compile_date_patterns(config)
    grace = config.reviewOverdueGraceDays
    results: dict[str, ExpiryFinding] = {}
    for doc in docs:
        text_dates = extract_text_dates(doc.text or "", patterns, config.textMaxChars)
        text_expirations = [item.value for item in text_dates if item.kind == KIND_EXPIRATION]
        text_reviews = [item.value for item in text_dates if item.kind == KIND_REVIEW]

        expiry_candidates: list[tuple[str, date]] = []
        if doc.metadata_expiration is not None:
            expiry_candidates.append((SOURCE_METADATA, doc.metadata_expiration))
        if text_expirations:
            expiry_candidates.append((SOURCE_TEXT, min(text_expirations)))
        expired_by = tuple(source for source, value in expiry_candidates if value < as_of)
        expiration_value = min((value for _, value in expiry_candidates), default=None)

        review_candidates: list[tuple[str, date]] = []
        if doc.metadata_review is not None:
            review_candidates.append((SOURCE_METADATA, doc.metadata_review))
        if text_reviews:
            review_candidates.append((SOURCE_TEXT, min(text_reviews)))
        overdue_by = tuple(
            source for source, value in review_candidates if (as_of - value).days > grace
        )
        review_value = doc.metadata_review or (min(text_reviews) if text_reviews else None)

        results[doc.key] = ExpiryFinding(
            key=doc.key,
            expired=bool(expired_by),
            expired_by=expired_by,
            expiration_date=expiration_value,
            days_past_expiration=(as_of - expiration_value).days if expired_by and expiration_value else None,
            review_date=review_value,
            review_overdue=bool(overdue_by),
            overdue_by=overdue_by,
            days_overdue=(
                (as_of - min(value for _, value in review_candidates)).days
                if overdue_by and review_candidates
                else None
            ),
            text_dates=text_dates,
        )
    return results
