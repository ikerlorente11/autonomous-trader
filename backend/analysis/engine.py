"""AnalysisEngine: the scoring pipeline seam and its Phase-4 implementation.

The engine composes the stages — per-symbol indicator compute -> composite -> rank —
keeping ``CompositeScorer`` and ``SymbolRanker`` as separate injectable units
(synthesis §6). The scheduler's ``run_analysis`` job depends on this Protocol. Inputs
are pandas frames of OHLCV bars (the metrics layer already speaks pandas); outputs are
the typed contracts. No weights or thresholds live here — those are config
(``config/strategy.yaml``), loaded once into a ``StrategyConfig``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from backend.analysis.config import StrategyConfig, load_strategy_config
from backend.analysis.indicators.base import Indicator
from backend.analysis.indicators.momentum import RelativeStrengthIndex
from backend.analysis.indicators.moving_average import (
    ExponentialMovingAverage,
    SimpleMovingAverage,
)
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator
from backend.analysis.scoring.composite_scorer import WeightedCompositeScorer
from backend.analysis.scoring.symbol_ranker import ScoreRanker
from backend.contracts import IndicatorResult, RankedSymbol, SymbolScore

if TYPE_CHECKING:
    from pandas import DataFrame


@runtime_checkable
class AnalysisEngine(Protocol):
    def compute_indicators(
        self, bars: Mapping[str, DataFrame], asof: dt.datetime
    ) -> list[IndicatorResult]: ...

    def score_symbol(
        self, symbol: str, bars: DataFrame, asof: dt.datetime
    ) -> SymbolScore: ...

    def rank_symbols(self, scores: list[SymbolScore]) -> list[RankedSymbol]: ...


def _build_indicators(config: StrategyConfig) -> list[Indicator]:
    ma_cfg = config.indicators.ma_trend
    ma_cls = SimpleMovingAverage if ma_cfg.kind == "sma" else ExponentialMovingAverage
    rsi_cfg = config.indicators.rsi
    atr_cfg = config.indicators.atr
    return [
        ma_cls(
            period=ma_cfg.period,
            sensitivity=ma_cfg.sensitivity,
            extension_cap=ma_cfg.extension_cap,
        ),
        RelativeStrengthIndex(
            period=rsi_cfg.period,
            overbought=rsi_cfg.overbought,
            oversold=rsi_cfg.oversold,
            mode=rsi_cfg.mode,
        ),
        AverageTrueRangeIndicator(period=atr_cfg.period, sensitivity=atr_cfg.sensitivity),
    ]


class DefaultAnalysisEngine:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self._config = config or load_strategy_config()
        self._indicators = _build_indicators(self._config)
        self._scorer = WeightedCompositeScorer(self._config)
        self._ranker = ScoreRanker(self._config)

    @property
    def strategy_version(self) -> str:
        return self._config.strategy_version

    def _symbol_indicators(
        self, symbol: str, bars: DataFrame, asof: dt.datetime
    ) -> list[IndicatorResult]:
        results: list[IndicatorResult] = []
        for indicator in self._indicators:
            sub_score = indicator.latest_score(bars)
            if sub_score is None:
                continue
            results.append(
                IndicatorResult(
                    symbol=symbol,
                    ts=asof,
                    signal_id=indicator.signal_id,
                    value=Decimal(str(round(sub_score, 8))),
                )
            )
        return results

    def compute_indicators(
        self, bars: Mapping[str, DataFrame], asof: dt.datetime
    ) -> list[IndicatorResult]:
        out: list[IndicatorResult] = []
        for symbol, frame in bars.items():
            out.extend(self._symbol_indicators(symbol, frame, asof))
        return out

    def score_symbol(
        self, symbol: str, bars: DataFrame, asof: dt.datetime
    ) -> SymbolScore:
        indicators = self._symbol_indicators(symbol, bars, asof)
        return self._scorer.score(symbol, indicators, asof)

    def rank_symbols(self, scores: list[SymbolScore]) -> list[RankedSymbol]:
        return self._ranker.rank(scores)
