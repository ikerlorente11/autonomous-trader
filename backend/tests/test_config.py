"""Tests for strategy config loading, env overrides, and version determinism."""

from __future__ import annotations

import pytest

from backend.analysis import config as cfg


@pytest.fixture
def config_path(tmp_path):
    yaml_text = """
version: "0.1.0"
ranker:
  min_score_to_act: 60.0
  min_score_to_exit: 45.0
  min_data_completeness: 0.5
scoring:
  score_min: 0.0
  score_max: 100.0
  weights:
    rsi: 0.5
    ma_trend: 0.3
    atr: 0.2
indicators:
  ma_trend:
    kind: ema
    period: 20
    sensitivity: 20.0
  rsi:
    period: 14
    overbought: 70.0
    oversold: 30.0
  atr:
    period: 14
    sensitivity: 50.0
"""
    p = tmp_path / "strategy.yaml"
    p.write_text(yaml_text)
    return p


@pytest.fixture(autouse=True)
def _clear_cache():
    cfg._cached.cache_clear()
    yield
    cfg._cached.cache_clear()


def test_loads_yaml_defaults(config_path) -> None:
    c = cfg.load_strategy_config(config_path)
    assert c.version == "0.1.0"
    assert c.ranker.min_score_to_act == 60.0
    assert c.scoring.weights["rsi"] == 0.5
    assert c.indicators.ma_trend.kind == "ema"


def test_env_override_nested_leaf(config_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATEGY__RANKER__MIN_SCORE_TO_ACT", "70")
    cfg._cached.cache_clear()
    c = cfg.load_strategy_config(config_path)
    assert c.ranker.min_score_to_act == 70.0


def test_env_override_deep_weight(config_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATEGY__SCORING__WEIGHTS__RSI", "0.9")
    cfg._cached.cache_clear()
    c = cfg.load_strategy_config(config_path)
    assert c.scoring.weights["rsi"] == 0.9


def test_config_hash_deterministic(config_path) -> None:
    c1 = cfg.load_strategy_config(config_path)
    cfg._cached.cache_clear()
    c2 = cfg.load_strategy_config(config_path)
    assert c1.config_hash == c2.config_hash
    assert len(c1.config_hash) == 6


def test_strategy_version_format(config_path) -> None:
    c = cfg.load_strategy_config(config_path)
    assert c.strategy_version == f"0.1.0+{c.config_hash}"


def test_config_hash_changes_with_override(
    config_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = cfg.load_strategy_config(config_path).config_hash
    monkeypatch.setenv("STRATEGY__RANKER__MIN_SCORE_TO_ACT", "70")
    cfg._cached.cache_clear()
    overridden = cfg.load_strategy_config(config_path).config_hash
    assert base != overridden


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        cfg.load_strategy_config(tmp_path / "nope.yaml")
