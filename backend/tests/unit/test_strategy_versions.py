"""Strategy version overlays (config/strategies/*.yaml) — the per-portfolio A/B seam."""

from __future__ import annotations

import pytest

from backend.analysis.config import list_strategy_versions, load_strategy_config

pytestmark = pytest.mark.unit


def test_lists_v1_and_v2() -> None:
    versions = list_strategy_versions()
    assert "v1" in versions
    assert "v2" in versions
    assert "v3" in versions
    assert "v4" in versions
    assert "v5" in versions
    assert "v6" in versions


def test_v2_drops_atr_from_score() -> None:
    base = load_strategy_config()
    v2 = load_strategy_config(label="v2")
    assert base.scoring.weights["atr"] == 0.20  # base keeps ATR
    assert v2.scoring.weights["atr"] == 0.0  # v2 removes it
    assert v2.scoring.weights["rsi"] == base.scoring.weights["rsi"]  # other weights untouched
    assert v2.strategy_version != base.strategy_version  # distinct version hash


def test_v1_overlay_equals_base() -> None:
    # v1 is an explicit no-op control arm: same resolved config as the base.
    assert load_strategy_config(label="v1").strategy_version == load_strategy_config().strategy_version


def test_v2_applies_all_diagnostics_fixes() -> None:
    v2 = load_strategy_config(label="v2")
    assert v2.indicators.rsi.mode == "mean_reversion"  # P4
    assert v2.indicators.ma_trend.extension_cap == 0.02  # P5
    assert v2.trading.stop_reentry_cooldown_days == 3  # P2
    assert v2.trading.stop_min_distance_pct == 0.05  # P3
    assert v2.trading.allow_pyramiding is False  # P6


def test_v3_is_v2_plus_rank_normalize() -> None:
    # v3 = v2 + P7 (rank-normalization), so the A/B isolates the v3 delta over v2.
    base = load_strategy_config()
    v2 = load_strategy_config(label="v2")
    v3 = load_strategy_config(label="v3")
    assert base.scoring.rank_normalize is False  # off in base/v1/v2
    assert v2.scoring.rank_normalize is False
    assert v3.scoring.rank_normalize is True  # the v3 delta
    # inherits every v2 fix unchanged
    assert v3.scoring.weights["atr"] == 0.0
    assert v3.indicators.rsi.mode == "mean_reversion"
    assert v3.indicators.ma_trend.extension_cap == 0.02
    assert v3.trading.stop_reentry_cooldown_days == 3
    assert v3.trading.stop_min_distance_pct == 0.05
    assert v3.trading.allow_pyramiding is False
    assert v3.strategy_version != v2.strategy_version  # distinct version hash


def test_v4_is_v3_plus_momentum_weight() -> None:
    # v4 = v3 + P11 phase 1 (cross-sectional momentum in the composite). The base
    # carries the indicator params but NO weight — observation mode only.
    base = load_strategy_config()
    v3 = load_strategy_config(label="v3")
    v4 = load_strategy_config(label="v4")
    assert "momentum" not in base.scoring.weights
    assert "momentum" not in v3.scoring.weights
    assert v4.scoring.weights["momentum"] == 0.40  # the v4 delta
    assert base.indicators.momentum is not None  # params live in the base
    assert v4.indicators.momentum == base.indicators.momentum
    # inherits every v3 fix unchanged
    assert v4.scoring.rank_normalize is True
    assert v4.scoring.weights["atr"] == 0.0
    assert v4.indicators.rsi.mode == "mean_reversion"
    assert v4.indicators.ma_trend.extension_cap == 0.02
    assert v4.trading.stop_reentry_cooldown_days == 3
    assert v4.trading.allow_pyramiding is False
    assert v4.strategy_version != v3.strategy_version  # distinct version hash


def test_base_trading_defaults_are_unset() -> None:
    # Base ("v1") leaves execution untouched: every trading knob falls back to env/default.
    base = load_strategy_config()
    assert base.indicators.rsi.mode == "passthrough"
    assert base.indicators.ma_trend.extension_cap is None
    assert base.trading.stop_reentry_cooldown_days is None
    assert base.trading.allow_pyramiding is None


def test_unknown_label_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_strategy_config(label="does-not-exist")

def test_v5_is_v4_plus_regime_multiplier() -> None:
    # v5 = v4 + P11 phase 2 (macro regime multiplier). Off everywhere below v5.
    v4 = load_strategy_config(label="v4")
    v5 = load_strategy_config(label="v5")
    assert v4.scoring.regime_multiplier is None
    assert v5.scoring.regime_multiplier is not None  # the v5 delta
    assert v5.scoring.regime_multiplier.floor == 0.75
    assert v5.scoring.regime_multiplier.ceil == 1.05
    # inherits every v4 piece unchanged
    assert v5.scoring.weights["momentum"] == 0.40
    assert v5.scoring.rank_normalize is True
    assert v5.indicators.rsi.mode == "mean_reversion"
    assert v5.trading.allow_pyramiding is False
    assert v5.strategy_version != v4.strategy_version


def test_v6_is_v5_plus_fundamental_weights() -> None:
    # v6 = v5 + fundamentals activation (quality / revenue_accel / earnings_accel).
    v5 = load_strategy_config(label="v5")
    v6 = load_strategy_config(label="v6")
    for sid in ("quality", "revenue_accel", "earnings_accel"):
        assert sid not in v5.scoring.weights
    assert v6.scoring.weights["quality"] == 0.15  # the v6 delta
    assert v6.scoring.weights["revenue_accel"] == 0.10
    assert v6.scoring.weights["earnings_accel"] == 0.10
    # inherits every v5 piece unchanged
    assert v6.scoring.regime_multiplier == v5.scoring.regime_multiplier
    assert v6.scoring.weights["momentum"] == 0.40
    assert v6.scoring.rank_normalize is True
    assert v6.strategy_version != v5.strategy_version
