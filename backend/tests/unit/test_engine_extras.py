"""P11 plumbing — extra signals and the macro regime multiplier in score_universe."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backend.analysis.config import (
    MarketFilterConfig,
    RankerConfig,
    load_strategy_config,
)
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


def _trend_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=len(closes), freq="D")
    c = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1_000_000}, index=idx
    )


def _engine_with_filter(ma_period: int = 5):
    base = load_strategy_config()
    cfg = base.model_copy(
        update={
            "ranker": RankerConfig(
                min_score_to_act=base.ranker.min_score_to_act,
                min_score_to_exit=base.ranker.min_score_to_exit,
                min_data_completeness=base.ranker.min_data_completeness,
                market_filter=MarketFilterConfig(benchmark="SPY", ma_period=ma_period, kind="sma"),
            )
        }
    )
    return DefaultAnalysisEngine(cfg)


def test_market_filter_blocks_entries_in_downtrend() -> None:
    # SPY below its MA: a strong name that would BUY is downgraded to HOLD.
    up = [100.0] * 10 + [101, 102, 103, 104, 105]      # AAA: clearly above its MA -> BUY
    spy_down = [200.0 - i for i in range(15)]           # SPY: falling -> below MA
    engine = _engine_with_filter(ma_period=5)
    _, scores = engine.score_universe(
        {"AAA": _trend_frame(up), "SPY": _trend_frame(spy_down)}, ASOF
    )
    aaa = next(s for s in scores if s.symbol == "AAA")
    assert aaa.action.value == "hold"
    assert "market filter" in (aaa.reason or "")


def test_market_filter_allows_entries_in_uptrend() -> None:
    up = [100.0] * 10 + [101, 102, 103, 104, 105]
    spy_up = [100.0 + i for i in range(15)]             # SPY rising -> above MA
    engine = _engine_with_filter(ma_period=5)
    no_filter = DefaultAnalysisEngine(load_strategy_config())
    frames = {"AAA": _trend_frame(up), "SPY": _trend_frame(spy_up)}
    _, filtered = engine.score_universe(frames, ASOF)
    _, plain = no_filter.score_universe(frames, ASOF)
    a_f = next(s for s in filtered if s.symbol == "AAA")
    a_p = next(s for s in plain if s.symbol == "AAA")
    assert a_f.action == a_p.action  # uptrend -> filter is a no-op


def test_market_filter_fails_open_without_benchmark() -> None:
    # No SPY in the universe: entries are allowed (never block on missing data).
    up = [100.0] * 10 + [101, 102, 103, 104, 105]
    engine = _engine_with_filter(ma_period=5)
    _, scores = engine.score_universe({"AAA": _trend_frame(up)}, ASOF)
    assert "market filter" not in (scores[0].reason or "")
