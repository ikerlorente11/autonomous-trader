"""Unit tests for WeightedCompositeScorer (pure: no DataFrames, no DB)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.analysis.config import StrategyConfig
from backend.analysis.scoring.composite_scorer import WeightedCompositeScorer
from backend.contracts import IndicatorResult, SignalAction

ASOF = dt.datetime(2026, 1, 2, 12, 0, 0)


def _ind(signal_id: str, value: float) -> IndicatorResult:
    return IndicatorResult(
        symbol="AAA", ts=ASOF, signal_id=signal_id, value=Decimal(str(value))
    )


def test_full_coverage_weighted_average_and_completeness(
    strategy_config: StrategyConfig,
) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    indicators = [_ind("rsi", 80), _ind("ma_trend", 70), _ind("atr", 60)]
    result = scorer.score("AAA", indicators, ASOF)
    # 0.5*80 + 0.3*70 + 0.2*60 = 73.0 (weights already sum to 1.0).
    assert result.score == Decimal("73.0000")
    assert result.data_completeness == Decimal("1.0000")
    assert result.action is SignalAction.BUY


def test_missing_indicator_renormalizes_remaining_weights(
    strategy_config: StrategyConfig,
) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    # atr missing: present weights rsi(0.5)+ma_trend(0.3)=0.8.
    # raw = (0.5*80 + 0.3*70)/0.8 = 61/0.8 = 76.25; completeness = 0.8/1.0 = 0.8.
    result = scorer.score("AAA", [_ind("rsi", 80), _ind("ma_trend", 70)], ASOF)
    assert result.score == Decimal("76.2500")
    assert result.data_completeness == Decimal("0.8000")
    assert result.action is SignalAction.BUY


def test_unknown_signal_id_recorded_but_unweighted(
    strategy_config: StrategyConfig,
) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    indicators = [_ind("rsi", 80), _ind("not_a_signal", 100)]
    result = scorer.score("AAA", indicators, ASOF)
    # Only rsi weighs in: raw = 80; completeness = 0.5/1.0 = 0.5.
    assert result.score == Decimal("80.0000")
    assert result.data_completeness == Decimal("0.5000")
    assert "not_a_signal" in (result.indicator_snapshot or {})


def test_score_clipped_to_max(strategy_config: StrategyConfig) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    result = scorer.score("AAA", [_ind("rsi", 150)], ASOF)
    assert result.score == Decimal("100.0000")


def test_score_clipped_to_min(strategy_config: StrategyConfig) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    result = scorer.score("AAA", [_ind("rsi", -50)], ASOF)
    assert result.score == Decimal("0.0000")


def test_no_known_indicators_falls_back_to_score_min(
    strategy_config: StrategyConfig,
) -> None:
    # Zero coverage is zero information, not a low score: the action must be HOLD,
    # never SELL — a data outage must not liquidate a held position.
    scorer = WeightedCompositeScorer(strategy_config)
    result = scorer.score("AAA", [_ind("not_a_signal", 99)], ASOF)
    assert result.score == Decimal("0.0000")
    assert result.data_completeness == Decimal("0.0000")
    assert result.action is SignalAction.HOLD


def test_action_hold_in_hysteresis_band(strategy_config: StrategyConfig) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    # 50 is between exit(45) and act(60).
    result = scorer.score("AAA", [_ind("rsi", 50)], ASOF)
    assert result.action is SignalAction.HOLD


def test_action_sell_at_or_below_exit(strategy_config: StrategyConfig) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    result = scorer.score("AAA", [_ind("rsi", 45)], ASOF)
    assert result.action is SignalAction.SELL


@pytest.mark.parametrize("rsi_value", [80, 90])
def test_low_coverage_gate_suppresses_buy_to_hold(
    strategy_config: StrategyConfig, rsi_value: float
) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    # Only ma_trend present -> completeness 0.3 < min_data_completeness 0.5.
    # ma_trend alone yields a BUY-worthy score, but coverage gate forces HOLD.
    result = scorer.score("AAA", [_ind("ma_trend", rsi_value)], ASOF)
    assert float(result.data_completeness or 0) < 0.5
    assert float(result.score) >= strategy_config.ranker.min_score_to_act
    assert result.action is SignalAction.HOLD


def test_low_coverage_does_not_block_sell(strategy_config: StrategyConfig) -> None:
    scorer = WeightedCompositeScorer(strategy_config)
    # Single low score -> SELL; coverage gate only suppresses entries, not exits.
    result = scorer.score("AAA", [_ind("atr", 10)], ASOF)
    assert float(result.data_completeness or 0) < 0.5
    assert result.action is SignalAction.SELL


def test_multiplier_scales_score_before_thresholds(
    strategy_config: StrategyConfig,
) -> None:
    # P11 phase 2: the regime multiplier damps/boosts the blended score; the
    # action gates then apply to the scaled value.
    scorer = WeightedCompositeScorer(strategy_config)
    base = scorer.score("AAA", [_ind("rsi", 80)], ASOF)
    damped = scorer.score("AAA", [_ind("rsi", 80)], ASOF, multiplier=0.75)
    assert damped.score == Decimal("60.0000")  # 80 * 0.75
    assert base.score == Decimal("80.0000")
    boosted = scorer.score("AAA", [_ind("rsi", 99)], ASOF, multiplier=1.05)
    assert boosted.score == Decimal("100.0000")  # clipped at score_max
