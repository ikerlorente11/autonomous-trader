"""Sentiment signal — news buzz (abnormal news flow).

Pure: maps a symbol's recent daily article counts to a 0–100 score by how far the
latest day's volume sits above its own recent baseline (z-score → logistic). High
score = unusual news attention today. Needs a minimum history; returns ``None``
otherwise (dropped, never imputed). Temperature and history window are env-tunable.

This is news *flow*, not polarity — a Tier-2 attention signal (synthesis). It is
recorded as a ``signal_value`` in observation mode, not fed to the composite scorer.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence

NEWS_BUZZ_SIGNAL_ID = "news_buzz"


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def news_buzz_score(counts: Sequence[float | int | None]) -> float | None:
    """0–100 logistic of the latest day's article-count z-score vs prior days."""
    values = [float(c) for c in counts if c is not None]
    min_history = int(_float_env("NEWS_BUZZ_MIN_HISTORY", 4))
    if len(values) < min_history + 1:
        return None
    latest, baseline = values[-1], values[:-1]
    mean = sum(baseline) / len(baseline)
    variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
    std = math.sqrt(variance)
    if std == 0:
        if latest == mean:
            return 50.0
        return 100.0 if latest > mean else 0.0
    temp = _float_env("NEWS_BUZZ_TEMP", 1.0)
    if temp <= 0:
        return 50.0
    z = (latest - mean) / std
    return 100.0 / (1.0 + math.exp(-z / temp))
