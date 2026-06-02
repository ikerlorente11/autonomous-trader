"""Unit tests for ScoreRanker (pure: list filtering + ordering)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from backend.analysis.config import StrategyConfig
from backend.analysis.scoring.symbol_ranker import ScoreRanker
from backend.contracts import SignalAction, SymbolScore

ASOF = dt.datetime(2026, 1, 2, 12, 0, 0)


def _score(symbol: str, score: float, completeness: float | None = 1.0) -> SymbolScore:
    return SymbolScore(
        symbol=symbol,
        ts=ASOF,
        score=Decimal(str(score)),
        action=SignalAction.BUY,
        data_completeness=None if completeness is None else Decimal(str(completeness)),
    )


def test_orders_by_score_descending(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank([_score("LOW", 65), _score("HIGH", 90), _score("MID", 75)])
    assert [r.score.symbol for r in out] == ["HIGH", "MID", "LOW"]
    assert [r.rank for r in out] == [1, 2, 3]


def test_drops_below_min_score(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank([_score("KEEP", 60), _score("DROP", 59.99)])
    assert [r.score.symbol for r in out] == ["KEEP"]


def test_drops_low_completeness(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank([_score("KEEP", 80, 0.5), _score("DROP", 95, 0.49)])
    assert [r.score.symbol for r in out] == ["KEEP"]


def test_none_completeness_is_kept(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank([_score("KEEP", 80, None)])
    assert [r.score.symbol for r in out] == ["KEEP"]


def test_exclude_set_removes_symbol(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank(
        [_score("AAA", 90), _score("BBB", 85)], exclude=frozenset({"AAA"})
    )
    assert [r.score.symbol for r in out] == ["BBB"]


def test_tie_break_by_completeness_then_symbol(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    out = ranker.rank(
        [
            _score("AAA", 80, 0.9),
            _score("BBB", 80, 1.0),
            _score("CCC", 80, 0.9),
        ]
    )
    # Equal score: higher completeness first (BBB), then symbol desc (CCC > AAA).
    assert [r.score.symbol for r in out] == ["BBB", "CCC", "AAA"]


def test_empty_input_yields_empty(strategy_config: StrategyConfig) -> None:
    ranker = ScoreRanker(strategy_config)
    assert ranker.rank([]) == []
