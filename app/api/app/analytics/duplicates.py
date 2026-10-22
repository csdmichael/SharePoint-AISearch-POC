"""Exact and near-duplicate clustering, canonical selection and conflict candidates.

Rules (governance-policy.json, similarity.note):
- Exact duplicates share the content digest of the normalized text.
- Near duplicates need cosine >= the near-duplicate threshold AND an identical numeric fingerprint.
- Same scope (product family, process area, document type) with divergent numbers and cosine >= the conflict
  threshold is a conflict candidate, not a duplicate.
- Each cluster has one canonical copy: authoritative first, then the newest effective date, then artifact id.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.config import DuplicateConfig, TfidfConfig


@dataclass(frozen=True)
class DupDoc:
    key: str
    name: str
    title: str
    artifact_id: str
    authoritative: bool
    effective: date | None
    text: str
    digest: str
    fingerprint: tuple[str, ...]
    scope: tuple[str, str, str]


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    kind: str
    canonical: str
    members: tuple[str, ...]
    similarity_min: float
    similarity_mean: float
    fingerprint: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ConflictCandidate:
    first: str
    second: str
    similarity: float
    scope: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DuplicateResult:
    exact: tuple[Cluster, ...]
    near: tuple[Cluster, ...]
    conflicts: tuple[ConflictCandidate, ...]
    parameters: dict[str, object]


def canonical_rank(doc: DupDoc) -> tuple:
    effective_ordinal = doc.effective.toordinal() if doc.effective else 0
    return (not doc.authoritative, doc.effective is None, -effective_ordinal, doc.artifact_id.lower(), doc.key)


def _similarity_matrix(
    texts: Sequence[str],
    tfidf: TfidfConfig,
) -> np.ndarray | None:
    vectorizer = TfidfVectorizer(
        ngram_range=(tfidf.ngramRange[0], tfidf.ngramRange[1]),
        min_df=tfidf.minDf,
        max_features=tfidf.maxFeatures,
        sublinear_tf=tfidf.sublinearTf,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return None
    return np.clip((matrix @ matrix.T).toarray(), -1.0, 1.0)


def analyze_duplicates(
    docs: Sequence[DupDoc],
    *,
    clustering: DuplicateConfig,
    tfidf: TfidfConfig,
    cosine_threshold: float,
    distance_threshold: float,
    conflict_cosine: float,
    vector_char_limit: int,
    exact_reason: str,
    near_reason: str,
    conflict_reason: str,
) -> DuplicateResult:
    minimum = clustering.minClusterSize
    groups: dict[str, list[DupDoc]] = defaultdict(list)
    for doc in docs:
        groups[doc.digest].append(doc)

    exact_raw: list[tuple[DupDoc, list[DupDoc]]] = []
    for members in groups.values():
        if len(members) >= minimum:
            ordered = sorted(members, key=canonical_rank)
            exact_raw.append((ordered[0], ordered))
    exact_raw.sort(key=lambda pair: canonical_rank(pair[0]))
    exact = tuple(
        Cluster(
            cluster_id=f"exact-{position:03d}",
            kind="exact",
            canonical=canonical.key,
            members=tuple(doc.key for doc in ordered),
            similarity_min=1.0,
            similarity_mean=1.0,
            fingerprint=canonical.fingerprint,
            reason=exact_reason,
        )
        for position, (canonical, ordered) in enumerate(exact_raw, start=1)
    )

    representatives = sorted((min(members, key=canonical_rank) for members in groups.values()), key=canonical_rank)
    similarity = (
        _similarity_matrix([rep.text[:vector_char_limit] for rep in representatives], tfidf)
        if len(representatives) >= 2
        else None
    )
    near_raw: list[tuple[DupDoc, list[int], list[float], list[DupDoc]]] = []
    conflicts: list[ConflictCandidate] = []
    if similarity is not None:
        by_fingerprint: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for index, rep in enumerate(representatives):
            by_fingerprint[rep.fingerprint].append(index)
        for indexes in by_fingerprint.values():
            if len(indexes) < minimum:
                continue
            block = similarity[np.ix_(indexes, indexes)]
            distance = np.clip(1.0 - block, 0.0, None)
            np.fill_diagonal(distance, 0.0)
            labels = AgglomerativeClustering(
                metric="precomputed",
                linkage=clustering.linkage,
                distance_threshold=distance_threshold,
                n_clusters=None,
            ).fit_predict(distance)
            for label in sorted(set(labels.tolist())):
                local = [indexes[position] for position, value in enumerate(labels) if value == label]
                if len(local) < minimum:
                    continue
                ordered = sorted(local, key=lambda idx: canonical_rank(representatives[idx]))
                canonical_index = ordered[0]
                kept = [
                    idx for idx in ordered
                    if idx == canonical_index or similarity[canonical_index, idx] >= cosine_threshold
                ]
                if len(kept) < minimum:
                    continue
                pairs = [similarity[a, b] for position, a in enumerate(kept) for b in kept[position + 1:]]
                expanded: list[DupDoc] = []
                for idx in kept:
                    expanded.extend(groups[representatives[idx].digest])
                expanded.sort(key=canonical_rank)
                near_raw.append((representatives[canonical_index], kept, pairs, expanded))

        for first in range(len(representatives)):
            for second in range(first + 1, len(representatives)):
                left, right = representatives[first], representatives[second]
                if left.scope != right.scope or left.fingerprint == right.fingerprint:
                    continue
                if not (left.authoritative or right.authoritative):
                    continue
                score = float(similarity[first, second])
                if score < conflict_cosine:
                    continue
                conflicts.append(
                    ConflictCandidate(
                        first=left.key,
                        second=right.key,
                        similarity=round(score, 4),
                        scope=left.scope,
                        reason=conflict_reason.format(similarity=f"{score:.3f}"),
                    )
                )

    near_raw.sort(key=lambda item: canonical_rank(item[0]))
    near: list[Cluster] = []
    for position, (canonical, kept, pairs, expanded) in enumerate(near_raw, start=1):
        near.append(
            Cluster(
                cluster_id=f"near-{position:03d}",
                kind="near",
                canonical=canonical.key,
                members=tuple(doc.key for doc in expanded),
                similarity_min=round(float(min(pairs)), 4),
                similarity_mean=round(float(sum(pairs) / len(pairs)), 4),
                fingerprint=canonical.fingerprint,
                reason=near_reason.format(similarity=f"{float(sum(pairs) / len(pairs)):.3f}"),
            )
        )

    return DuplicateResult(
        exact=exact,
        near=tuple(near),
        conflicts=tuple(conflicts),
        parameters={
            "cosineThreshold": cosine_threshold,
            "distanceThreshold": distance_threshold,
            "conflictCandidateCosine": conflict_cosine,
            "linkage": clustering.linkage,
            "minClusterSize": minimum,
            "tfidf": {
                "ngramRange": list(tfidf.ngramRange),
                "minDf": tfidf.minDf,
                "maxFeatures": tfidf.maxFeatures,
                "sublinearTf": tfidf.sublinearTf,
            },
            "vectorCharacterLimit": vector_char_limit,
        },
    )
