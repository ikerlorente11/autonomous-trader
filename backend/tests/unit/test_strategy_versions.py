"""Strategy version overlays (config/strategies/*.yaml) — the per-portfolio A/B seam."""

from __future__ import annotations

import pytest

from backend.analysis.config import list_strategy_versions, load_strategy_config

pytestmark = pytest.mark.unit


def test_lists_v1_and_v2() -> None:
    versions = list_strategy_versions()
    assert "v1" in versions
    assert "v2" in versions


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


def test_unknown_label_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_strategy_config(label="does-not-exist")
