"""News buzz signal — abnormal-flow z-score (pure)."""

from __future__ import annotations

import pytest

from backend.analysis.signals.sentiment.news import news_buzz_score

pytestmark = pytest.mark.unit


def test_spike_scores_high() -> None:
    s = news_buzz_score([1, 1, 2, 1, 10])  # latest well above baseline
    assert s is not None and s > 80.0


def test_quiet_day_scores_low() -> None:
    s = news_buzz_score([8, 9, 10, 9, 1])  # latest well below baseline
    assert s is not None and s < 20.0


def test_typical_day_near_fifty() -> None:
    # Baseline has variance; latest sits at the mean -> z = 0 -> ~50.
    s = news_buzz_score([4, 6, 5, 5, 5])
    assert s is not None and 40.0 <= s <= 60.0


def test_insufficient_history_is_none() -> None:
    assert news_buzz_score([1, 2, 3]) is None  # < min_history + 1
    assert news_buzz_score([]) is None


def test_zero_variance_baseline() -> None:
    assert news_buzz_score([5, 5, 5, 5, 5]) == pytest.approx(50.0)  # latest == mean
    assert news_buzz_score([5, 5, 5, 5, 9]) == pytest.approx(100.0)  # above flat base
    assert news_buzz_score([5, 5, 5, 5, 0]) == pytest.approx(0.0)  # below flat base


def test_none_counts_are_ignored() -> None:
    # Nones dropped; remaining still meets the min-history requirement.
    assert news_buzz_score([1, None, 1, 2, 1, 10]) is not None
