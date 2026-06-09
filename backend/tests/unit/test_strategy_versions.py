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
