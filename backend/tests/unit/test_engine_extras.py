"""P11 plumbing — extra signals and the macro regime multiplier in score_universe."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backend.analysis.config import load_strategy_config
from backend.analysis.engine import DefaultAnalysisEngine

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc
ASOF = dt.datetime(2026, 5, 29, tzinfo=UTC)


def _frames(*symbols: str) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    out = {}
    for i, sym in enumerate(symbols):
        close = pd.Series(range(100, 300), index=idx, dtype="float64") + i * 5
        out[sym] = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1, "close": close,
             "volume": 1_000_000},
            index=idx,
        )
    return out


def test_base_config_ignores_extras_and_regime() -> None:
    # No extra weights, no regime_multiplier: extras/regime must change nothing.
    engine = DefaultAnalysisEngine(load_strategy_config())
    frames = _frames("AAA", "BBB")
    _, plain = engine.score_universe(frames, ASOF)
    _, fed = engine.score_universe(
        frames, ASOF,
        extra_signals={"AAA": {"quality": 99.0}}, regime_score=0.0,
    )
    assert [(s.symbol, s.score) for s in plain] == [(s.symbol, s.score) for s in fed]


def test_v6_weights_extras_into_the_composite() -> None:
    engine = DefaultAnalysisEngine(load_strategy_config(label="v6"))
    frames = _frames("AAA", "BBB")
    extras_hi = {"AAA": {"quality": 100.0}, "BBB": {"quality": 0.0}}
    extras_lo = {"AAA": {"quality": 0.0}, "BBB": {"quality": 100.0}}
    _, hi = engine.score_universe(frames, ASOF, extra_signals=extras_hi)
    _, lo = engine.score_universe(frames, ASOF, extra_signals=extras_lo)
    score_hi = next(s.score for s in hi if s.symbol == "AAA")
    score_lo = next(s.score for s in lo if s.symbol == "AAA")
    assert score_hi > score_lo


def test_extras_never_returned_for_persistence() -> None:
    # The indicator list feeds persist_signal_values; extras are persisted by their
    # own producers, so returning them here would double-write.
    engine = DefaultAnalysisEngine(load_strategy_config(label="v6"))
    indicators, _ = engine.score_universe(
        _frames("AAA"), ASOF, extra_signals={"AAA": {"quality": 80.0}}
    )
    assert all(ind.signal_id != "quality" for ind in indicators)


def test_regime_multiplier_scales_scores_when_enabled() -> None:
    engine = DefaultAnalysisEngine(load_strategy_config(label="v5"))
    frames = _frames("AAA", "BBB")
    _, risk_on = engine.score_universe(frames, ASOF, regime_score=100.0)
    _, risk_off = engine.score_universe(frames, ASOF, regime_score=0.0)
    for on, off in zip(risk_on, risk_off):
        # floor 0.75 / ceil 1.05: risk-off damps every composite below risk-on.
        assert off.score < on.score


def test_regime_unknown_means_no_effect() -> None:
    engine = DefaultAnalysisEngine(load_strategy_config(label="v5"))
    frames = _frames("AAA")
    _, none_score = engine.score_universe(frames, ASOF, regime_score=None)
    _, neutral = engine.score_universe(frames, ASOF)
    assert none_score[0].score == neutral[0].score
