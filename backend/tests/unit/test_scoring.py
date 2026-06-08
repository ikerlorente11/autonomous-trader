"""WeightedCompositeScorer + ScoreRanker — pure, config-driven."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.analysis.config import load_strategy_config
from backend.analysis.scoring.composite_scorer import WeightedCompositeScorer
from backend.analysis.scoring.symbol_ranker import ScoreRanker
from backend.contracts import SignalAction
from backend.tests.factories import indicator, symbol_score

pytestmark = pytest.mark.unit

ASOF = dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def config():
    return load_strategy_config()


@pytest.fixture(scope="module")
def scorer(config):
    return WeightedCompositeScorer(config)


def test_all_signals_equal_gives_that_value_and_full_completeness(scorer) -> None:
    s = scorer.score("AAPL", [indicator("rsi", 80), indicator("ma_trend", 80), indicator("atr", 80)], ASOF)
    assert s.score == Decimal("80.0000")
    assert s.data_completeness == Decimal("1.0000")
    assert s.action == SignalAction.BUY  # >= 60


def test_missing_signal_renormalizes_weights(scorer) -> None:
    # atr weight is 0 (diagnostics P1) so total weight is 0.8; only rsi (0.5) present
    # -> completeness 0.5/0.8 = 0.625, score = rsi value.
    s = scorer.score("AAPL", [indicator("rsi", 80)], ASOF)
    assert s.score == Decimal("80.0000")
    assert s.data_completeness == Decimal("0.6250")


def test_weighted_average_lands_in_hold_band(scorer) -> None:
    # atr weight is 0 (diagnostics P1): (rsi70*.5 + ma40*.3)/0.8 = 47/0.8 = 58.75
    # -> between exit(45) and act(60) -> HOLD. atr value is snapshotted but unweighted.
    s = scorer.score("AAPL", [indicator("rsi", 70), indicator("ma_trend", 40), indicator("atr", 10)], ASOF)
    assert s.score == Decimal("58.7500")
    assert s.action == SignalAction.HOLD


def test_low_score_is_sell(scorer) -> None:
    s = scorer.score("AAPL", [indicator("rsi", 30), indicator("ma_trend", 30), indicator("atr", 30)], ASOF)
    assert s.action == SignalAction.SELL  # <= 45


def test_score_is_clipped_to_bounds(scorer) -> None:
    s = scorer.score("AAPL", [indicator("rsi", 150)], ASOF)
    assert s.score == Decimal("100.0000")  # score_max


def test_unknown_signal_id_is_snapshotted_but_not_weighted(scorer) -> None:
    s = scorer.score("AAPL", [indicator("rsi", 80), indicator("foo", 5)], ASOF)
    assert s.score == Decimal("80.0000")          # foo ignored in weighting
    assert "foo" in (s.indicator_snapshot or {})  # but kept in snapshot


# ---- ranker ----


def test_ranker_filters_by_min_score_and_orders_desc(config) -> None:
    ranker = ScoreRanker(config)
    out = ranker.rank([symbol_score("LOW", 55), symbol_score("HIGH", 70), symbol_score("MID", 65)])
    assert [r.score.symbol for r in out] == ["HIGH", "MID"]  # LOW (55<60) dropped, sorted desc
    assert [r.rank for r in out] == [1, 2]


def test_ranker_excludes_flagged_symbols(config) -> None:
    ranker = ScoreRanker(config)
    out = ranker.rank([symbol_score("A", 90), symbol_score("B", 80)], exclude=frozenset({"A"}))
    assert [r.score.symbol for r in out] == ["B"]


def test_ranker_drops_low_completeness(config) -> None:
    ranker = ScoreRanker(config)
    out = ranker.rank([symbol_score("A", 90, completeness=0.4), symbol_score("B", 90, completeness=0.9)])
    assert [r.score.symbol for r in out] == ["B"]  # A below min_data_completeness 0.5
