"""P7 — cross-sectional rank-normalization of sub-scores (engine layer)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from backend.analysis.config import load_strategy_config
from backend.analysis.engine import (
    DefaultAnalysisEngine,
    _percentile_ranks,
    rank_normalize_results,
)
from backend.tests.factories import indicator

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc
ASOF = dt.datetime(2026, 5, 29, tzinfo=UTC)


def test_percentile_ranks_min_zero_max_hundred() -> None:
    assert _percentile_ranks([10.0, 20.0, 30.0]) == [0.0, 50.0, 100.0]


def test_percentile_ranks_handles_ties_with_average_rank() -> None:
    # two tied lows share average rank (0.5/2*100=25), the high is 100.
    assert _percentile_ranks([10.0, 10.0, 30.0]) == [25.0, 25.0, 100.0]


def test_percentile_ranks_degenerate_cases() -> None:
    assert _percentile_ranks([42.0]) == [50.0]  # single -> midpoint
    assert _percentile_ranks([]) == []
    assert _percentile_ranks([5.0, 5.0, 5.0]) == [50.0, 50.0, 50.0]  # all equal -> midpoint


def test_rank_normalize_replaces_target_signal_with_percentile() -> None:
    per_symbol = {
        "A": [indicator("rsi", 80, symbol="A")],
        "B": [indicator("rsi", 20, symbol="B")],
        "C": [indicator("rsi", 50, symbol="C")],
    }
    out = rank_normalize_results(per_symbol, {"rsi"})
    assert out["B"][0].value == Decimal("0E-8")  # lowest -> 0th percentile
    assert out["C"][0].value == Decimal("50.00000000")
    assert out["A"][0].value == Decimal("100.00000000")  # highest -> 100th


def test_rank_normalize_leaves_non_target_signals_untouched() -> None:
    per_symbol = {
        "A": [indicator("rsi", 80, symbol="A"), indicator("ma_trend", 10, symbol="A")],
        "B": [indicator("rsi", 20, symbol="B"), indicator("ma_trend", 90, symbol="B")],
    }
    out = rank_normalize_results(per_symbol, {"rsi"})  # only rsi is a target
    ma = {r.signal_id: r.value for r in out["A"]}["ma_trend"]
    assert ma == Decimal("10")  # ma_trend passes through unchanged


def test_rank_normalize_only_over_symbols_that_have_the_signal() -> None:
    # B lacks rsi: the percentile is computed over {A, C} only, never imputing B.
    per_symbol = {
        "A": [indicator("rsi", 30, symbol="A")],
        "B": [indicator("ma_trend", 99, symbol="B")],
        "C": [indicator("rsi", 70, symbol="C")],
    }
    out = rank_normalize_results(per_symbol, {"rsi"})
    assert out["A"][0].value == Decimal("0E-8")
    assert out["C"][0].value == Decimal("100.00000000")
    assert out["B"][0].value == Decimal("99")  # untouched


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = [dt.datetime(2026, 1, 1, tzinfo=UTC) + dt.timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def test_score_universe_off_equals_per_symbol_scoring() -> None:
    # With rank_normalize off (base config), score_universe must match score_symbol.
    engine = DefaultAnalysisEngine(load_strategy_config())
    up = _frame([100 + i for i in range(30)])
    down = _frame([100 - i * 0.5 for i in range(30)])
    bars = {"UP": up, "DOWN": down}
    _, scores = engine.score_universe(bars, ASOF)
    by_symbol = {s.symbol: s.score for s in scores}
    assert by_symbol["UP"] == engine.score_symbol("UP", up, ASOF).score
    assert by_symbol["DOWN"] == engine.score_symbol("DOWN", down, ASOF).score


def test_score_universe_rank_normalize_changes_the_composite() -> None:
    # The v3 overlay enables rank_normalize; the same universe must score differently
    # than the base, proving the flag is wired through the engine.
    base = DefaultAnalysisEngine(load_strategy_config())
    v3 = DefaultAnalysisEngine(load_strategy_config(label="v3"))
    bars = {
        "UP": _frame([100 + i for i in range(30)]),
        "DOWN": _frame([130 - i for i in range(30)]),
        "FLAT": _frame([100 + (i % 2) for i in range(30)]),
    }
    base_scores = {s.symbol: s.score for s in base.score_universe(bars, ASOF)[1]}
    v3_scores = {s.symbol: s.score for s in v3.score_universe(bars, ASOF)[1]}
    assert base_scores != v3_scores
    assert len(v3_scores) == 3
