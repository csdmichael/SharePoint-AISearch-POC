"""IsolationForest anomaly scoring with per-feature contributions.

The forest provides the score (fixed random_state for repeatable results). Per-feature contributions are a
robust z-score share (deviation from the median scaled by the median absolute deviation). They explain which
features pushed an item away from the population; they are not SHAP values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from sklearn.ensemble import IsolationForest

from app.core.config import AnomalyConfig

MAD_TO_SIGMA = 1.4826
ROUNDING = 4


@dataclass(frozen=True)
class AnomalyRow:
    key: str
    score: float
    rank: int
    is_anomaly: bool
    features: dict[str, float]
    contributions: dict[str, float]


def score_items(
    rows: Mapping[str, Mapping[str, float]],
    *,
    config: AnomalyConfig,
) -> list[AnomalyRow]:
    keys = sorted(rows)
    if len(keys) < 2:
        return []
    names: Sequence[str] = config.features
    matrix = np.array([[float(rows[key][name]) for name in names] for key in keys], dtype=float)

    model = IsolationForest(
        n_estimators=config.nEstimators,
        contamination=config.contamination,
        random_state=config.randomState,
    )
    model.fit(matrix)
    raw_scores = -model.score_samples(matrix)
    predictions = model.predict(matrix)

    median = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - median), axis=0) * MAD_TO_SIGMA
    spread = np.std(matrix, axis=0)
    scale = np.where(mad > 0, mad, np.where(spread > 0, spread, 1.0))
    deviation = np.abs(matrix - median) / scale
    totals = deviation.sum(axis=1, keepdims=True)
    shares = np.divide(deviation, totals, out=np.zeros_like(deviation), where=totals > 0)

    order = sorted(range(len(keys)), key=lambda index: (-raw_scores[index], keys[index]))
    result: list[AnomalyRow] = []
    for rank, index in enumerate(order, start=1):
        result.append(
            AnomalyRow(
                key=keys[index],
                score=round(float(raw_scores[index]), ROUNDING),
                rank=rank,
                is_anomaly=bool(predictions[index] == -1),
                features={name: round(float(matrix[index, column]), ROUNDING) for column, name in enumerate(names)},
                contributions={
                    name: round(float(shares[index, column]), ROUNDING) for column, name in enumerate(names)
                },
            )
        )
    return result
