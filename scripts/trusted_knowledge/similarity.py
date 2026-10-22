"""Similarity primitives: normalized text, content hashes, numeric facts, cosine and pair classification.

Patterns, the hash algorithm and the thresholds are passed in from the governance policy.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Sequence

EXACT = "exact"
NEAR = "near"
CONFLICT = "conflict"
PAIR_KINDS = (EXACT, NEAR, CONFLICT)
# Structural details of the normalized form and of hashing. They are not policy values.
NORMALIZED_SEPARATOR = " "
TEXT_ENCODING = "utf-8"


@dataclass(frozen=True)
class Signal:
    """Measurements for one document that pair classification compares."""

    key: str
    content_hash: str
    numeric_signature: tuple[str, ...]
    scope: tuple[str, str, str]
    authoritative_claim: bool
    supersedes: str | None
    vector: tuple[float, ...]


@dataclass(frozen=True)
class PairFinding:
    kind: str
    first: str
    second: str
    similarity: float

    def __post_init__(self) -> None:
        if self.kind not in PAIR_KINDS:
            raise ValueError(f"Unknown pair kind {self.kind!r}.")


def normalize_text(text: str, whitespace_pattern: re.Pattern[str]) -> str:
    return whitespace_pattern.sub(NORMALIZED_SEPARATOR, text).strip()


def content_hash(normalized_text: str, algorithm: str) -> str:
    return hashlib.new(algorithm, normalized_text.encode(TEXT_ENCODING)).hexdigest()


def numeric_signature(normalized_text: str, number_pattern: re.Pattern[str]) -> tuple[str, ...]:
    return tuple(sorted(match.group(0) for match in number_pattern.finditer(normalized_text)))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same dimensions.")
    magnitude = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    if magnitude == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / magnitude


def is_lineage_pair(first: Signal, second: Signal) -> bool:
    """A supersedes link between two documents. It blocks near-duplicate classification only."""
    return first.supersedes == second.key or second.supersedes == first.key


def classify_pairs(
    signals: Sequence[Signal],
    near_duplicate_cosine: float,
    conflict_cosine: float,
) -> list[PairFinding]:
    findings: list[PairFinding] = []
    for position, first in enumerate(signals):
        for second in signals[position + 1:]:
            similarity = cosine_similarity(first.vector, second.vector)
            if first.content_hash == second.content_hash:
                findings.append(PairFinding(EXACT, first.key, second.key, similarity))
                continue
            same_scope = first.scope == second.scope
            if same_scope and first.numeric_signature == second.numeric_signature:
                if similarity >= near_duplicate_cosine and not is_lineage_pair(first, second):
                    findings.append(PairFinding(NEAR, first.key, second.key, similarity))
                continue
            if same_scope and similarity >= conflict_cosine:
                if first.authoritative_claim or second.authoritative_claim:
                    findings.append(PairFinding(CONFLICT, first.key, second.key, similarity))
    return findings
