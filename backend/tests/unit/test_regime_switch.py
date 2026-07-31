"""v8 regime-switch ensemble — per-day sub-strategy selection in score_universe."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backend.analysis.config import (
    RegimeSwitchConfig,
    load_strategy_config,
)
from backend.analysis.engine import DefaultAnalysisEngine

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc
ASOF = dt.datetime(2026, 5, 29, tzinfo=UTC)


def _trend_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=len(closes), freq="D")
    c = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1_000_000},
        index=idx,
    )


def _universe(spy_closes: list[float]) -> dict[str, pd.DataFrame]:
    n = len(spy_closes)
    rising = [100.0 + i * 0.5 for i in range(n)]
    falling = [150.0 - i * 0.5 for i in range(n)]
    return {
        "AAA": _trend_frame(rising),
        "BBB": _trend_frame(falling),
        "SPY": _trend_frame(spy_closes),
    }


def _switch_engine(ma_period: int = 5) -> DefaultAnalysisEngine:
    cfg = load_strategy_config(label="v8").model_copy(
        update={
            "regime_switch": RegimeSwitchConfig(
                benchmark="SPY", ma_period=ma_period, kind="sma", trend="v1", chop="v3"
            )
        }
    )
    return DefaultAnalysisEngine(cfg)


def test_uptrend_scores_like_the_trend_leg() -> None:
    n = 60
    frames = _universe([100.0 + i for i in range(n)])  # SPY above its MA
    switch = _switch_engine()
    v1 = DefaultAnalysisEngine(load_strategy_config(label="v1"))
    _, switched = switch.score_universe(frames, ASOF)
    _, plain = v1.score_universe(frames, ASOF)
    assert [(s.symbol, s.score, s.action) for s in switched] == [
        (s.symbol, s.score, s.action) for s in plain
    ]


def test_downtrend_scores_like_the_chop_leg() -> None:
    n = 60
    frames = _universe([200.0 - i for i in range(n)])  # SPY below its MA
    switch = _switch_engine()
    v3 = DefaultAnalysisEngine(load_strategy_config(label="v3"))
    _, switched = switch.score_universe(frames, ASOF)
    _, plain = v3.score_universe(frames, ASOF)
    assert [(s.symbol, s.score, s.action) for s in switched] == [
        (s.symbol, s.score, s.action) for s in plain
    ]


def test_missing_benchmark_resolves_to_chop_leg() -> None:
    # Fail-open to the DEFENSIVE leg: no benchmark history -> v3 behaviour.
    n = 60
    frames = _universe([100.0] * n)
    frames.pop("SPY")
    switch = _switch_engine()
    v3 = DefaultAnalysisEngine(load_strategy_config(label="v3"))
    _, switched = switch.score_universe(frames, ASOF)
    _, plain = v3.score_universe(frames, ASOF)
    assert [(s.symbol, s.score) for s in switched] == [(s.symbol, s.score) for s in plain]


def test_nested_regime_switch_is_rejected() -> None:
    cfg = load_strategy_config(label="v8").model_copy(
        update={
            "regime_switch": RegimeSwitchConfig(
                benchmark="SPY", ma_period=5, kind="sma", trend="v8", chop="v3"
            )
        }
    )
    with pytest.raises(ValueError, match="nest"):
        DefaultAnalysisEngine(cfg)


def test_v8_overlay_loads_and_declares_switch() -> None:
    cfg = load_strategy_config(label="v8")
    assert cfg.regime_switch is not None
    assert cfg.regime_switch.trend == "v1"
    assert cfg.regime_switch.chop == "v3"
    # extras are the union of both legs (v1/v3 weight none today, so empty)
    assert DefaultAnalysisEngine(cfg).weighted_extra_ids() == set()


def test_active_leg_reports_the_scoring_leg() -> None:
    n = 60
    up = _universe([100.0 + i for i in range(n)])
    down = _universe([200.0 - i for i in range(n)])
    engine = _switch_engine()
    assert engine.active_leg(up) == "v1"
    assert engine.active_leg(down) == "v3"
    up.pop("SPY")
    assert engine.active_leg(up) == "v3"  # unknown trend -> defensive leg
    plain = DefaultAnalysisEngine(load_strategy_config(label="v3"))
    assert plain.active_leg(up) is None


def test_trading_from_leg_parses_and_defaults_off() -> None:
    # The v9 experiment was REJECTED by the two-window bake-off (the MA100 switch
    # classifies the 2026 sideways grind as trend, so the aggressive leg ran all
    # window — see docs/diagnostics/07-plan-v7-v8.md §v9). The MECHANISM stays,
    # tested and off by default, for a future version with a better regime detector.
    cfg = load_strategy_config(label="v8")
    assert cfg.regime_switch is not None
    assert cfg.regime_switch.trading_from_leg is False  # default: own knobs govern
    switched = cfg.model_copy(
        update={
            "regime_switch": cfg.regime_switch.model_copy(
                update={"trading_from_leg": True}
            )
        }
    )
    assert switched.regime_switch.trading_from_leg is True
    trend = load_strategy_config(label=cfg.regime_switch.trend)
    chop = load_strategy_config(label=cfg.regime_switch.chop)
    assert trend.trading.allow_pyramiding is None      # v1: pyramiding allowed (default)
    assert chop.trading.allow_pyramiding is False      # v3: disciplined


def test_confirm_momentum_gates_the_trend_leg() -> None:
    # v10: above the MA but NOT advancing (flat drift) must run the chop leg;
    # above the MA AND advancing runs the trend leg.
    n = 80
    cfg = load_strategy_config(label="v8").model_copy(
        update={
            "regime_switch": RegimeSwitchConfig(
                benchmark="SPY", ma_period=5, kind="sma", trend="v1", chop="v3",
                confirm_momentum_sessions=21,
            )
        }
    )
    engine = DefaultAnalysisEngine(cfg)
    rising = _universe([100.0 + i for i in range(n)])
    assert engine.active_leg(rising) == "v1"
    # Drift: rallies early, then holds a flat plateau above its short MA — the
    # 21-session return is ~0, so the confirmation fails.
    drift = _universe([100.0 + min(i, 40) * 1.0 for i in range(n)])
    assert engine.active_leg(drift) == "v3"
    # Not enough history for the confirmation window -> defensive leg.
    short = _universe([100.0 + i for i in range(15)])
    assert engine.active_leg(short) == "v3"
