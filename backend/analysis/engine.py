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
from backend.analysis.indicators.momentum import PriceMomentum, RelativeStrengthIndex
from backend.analysis.indicators.moving_average import (
    ExponentialMovingAverage,
    SimpleMovingAverage,
)
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator
from backend.analysis.scoring.composite_scorer import WeightedCompositeScorer
from backend.analysis.scoring.symbol_ranker import ScoreRanker
from backend.contracts import IndicatorResult, RankedSymbol, SignalAction, SymbolScore

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


def _percentile_ranks(values: list[float]) -> list[float]:
    """Map each value to its percentile rank in [0, 100] (min -> 0, max -> 100), with
    ties resolved to their average rank. A single value (or an all-equal set) maps to 50.
    Pure and in-memory over the day's universe — no history materialized (Pi RAM)."""
    n = len(values)
    if n <= 1:
        return [50.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [50.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        pct = avg_rank / (n - 1) * 100.0
        for k in range(i, j + 1):
            ranks[order[k]] = pct
        i = j + 1
    return ranks


def rank_normalize_results(
    per_symbol: dict[str, list[IndicatorResult]], signal_ids: set[str]
) -> dict[str, list[IndicatorResult]]:
    """Replace each target signal's value with its cross-sectional percentile rank
    across the universe (P7). Signals not in ``signal_ids`` (and symbols lacking a
    signal) pass through untouched; percentiles are computed only over symbols that
    have the signal, never imputing a missing one (synthesis §3.3)."""
    by_signal: dict[str, list[tuple[str, float]]] = {}
    for symbol, results in per_symbol.items():
        for res in results:
            if res.signal_id in signal_ids:
                by_signal.setdefault(res.signal_id, []).append((symbol, float(res.value)))
    normalized: dict[tuple[str, str], float] = {}
    for signal_id, pairs in by_signal.items():
        for (symbol, _), pct in zip(pairs, _percentile_ranks([v for _, v in pairs])):
            normalized[(symbol, signal_id)] = pct
    out: dict[str, list[IndicatorResult]] = {}
    for symbol, results in per_symbol.items():
        out[symbol] = [
            res.model_copy(
                update={"value": Decimal(str(round(normalized[(symbol, res.signal_id)], 8)))}
            )
            if (symbol, res.signal_id) in normalized
            else res
            for res in results
        ]
    return out


def _build_indicators(config: StrategyConfig) -> list[Indicator]:
    ma_cfg = config.indicators.ma_trend
    ma_cls = SimpleMovingAverage if ma_cfg.kind == "sma" else ExponentialMovingAverage
    rsi_cfg = config.indicators.rsi
    atr_cfg = config.indicators.atr
    indicators: list[Indicator] = [
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
    mom_cfg = config.indicators.momentum
    if mom_cfg is not None:
        indicators.append(
            PriceMomentum(
                period=mom_cfg.period, skip=mom_cfg.skip, sensitivity=mom_cfg.sensitivity
            )
        )
    return indicators


def _benchmark_above_ma(
    bars: Mapping[str, DataFrame], benchmark: str, ma_period: int, kind: str
) -> bool | None:
    """Whether the benchmark closes at/above its own MA. None = unknowable (benchmark
    absent or short history) — each caller picks its own fail-open behaviour."""
    df = bars.get(benchmark)
    if df is None or len(df) < ma_period:
        return None
    close = df["close"].astype(float)
    if kind == "ema":
        ma = close.ewm(span=ma_period, adjust=False).mean()
    else:
        ma = close.rolling(ma_period).mean()
    last_ma = ma.iloc[-1]
    if last_ma != last_ma:  # NaN guard
        return None
    return float(close.iloc[-1]) >= float(last_ma)


class DefaultAnalysisEngine:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self._config = config or load_strategy_config()
        self._indicators = _build_indicators(self._config)
        self._scorer = WeightedCompositeScorer(self._config)
        self._ranker = ScoreRanker(self._config)
        # v8: a regime-switch version delegates scoring to one of two full
        # sub-strategies chosen per day by the benchmark's primary trend.
        self._sub_engines: tuple[DefaultAnalysisEngine, DefaultAnalysisEngine] | None = None
        switch = self._config.regime_switch
        if switch is not None:
            trend_cfg = load_strategy_config(label=switch.trend)
            chop_cfg = load_strategy_config(label=switch.chop)
            if trend_cfg.regime_switch is not None or chop_cfg.regime_switch is not None:
                raise ValueError("regime_switch sub-strategies cannot nest a regime_switch")
            self._sub_engines = (
                DefaultAnalysisEngine(trend_cfg),
                DefaultAnalysisEngine(chop_cfg),
            )

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

    def _rank_normalize_targets(self) -> set[str]:
        return {sid for sid, w in self._config.scoring.weights.items() if w > 0}

    def weighted_extra_ids(self) -> set[str]:
        """Non-bar signal ids this version weights (e.g. ``quality`` in v6) — the
        extras a caller must supply for the composite to use them."""
        if self._sub_engines is not None:
            # Either leg may need extras depending on the day — the caller supplies
            # the union; the active leg merges only what it weights.
            return self._sub_engines[0].weighted_extra_ids() | self._sub_engines[1].weighted_extra_ids()
        bar_ids = {ind.signal_id for ind in self._indicators}
        return self._rank_normalize_targets() - bar_ids

    def _regime_multiplier(self, regime_score: float | None) -> float:
        cfg = self._config.scoring.regime_multiplier
        if cfg is None or regime_score is None:
            return 1.0
        clamped = max(0.0, min(100.0, regime_score))
        return cfg.floor + (cfg.ceil - cfg.floor) * clamped / 100.0

    def _market_uptrend(self, bars: Mapping[str, DataFrame]) -> bool:
        """True when the benchmark closes at/above its long MA — i.e. it is a "good
        moment" to be opening positions. Fail-open: True when the filter is off or
        the benchmark lacks enough history (never block entries on missing data)."""
        cfg = self._config.ranker.market_filter
        if cfg is None:
            return True
        above = _benchmark_above_ma(bars, cfg.benchmark, cfg.ma_period, cfg.kind)
        return True if above is None else above

    def active_leg(self, bars: Mapping[str, DataFrame]) -> str | None:
        """Label of the regime-switch leg that scores today; None for plain versions.
        Unknown trend resolves to the chop leg (the defensive one). Exposed so the
        execution layer can adopt the leg's ENTRY discipline (trading_from_leg, v9).

        v10: with ``confirm_momentum_sessions`` set, being above the MA is not
        enough — the benchmark must also have ADVANCED over that window
        (return > confirm_min_return), so a market drifting sideways above its
        still-rising average runs the defensive leg."""
        if self._sub_engines is None:
            return None
        switch = self._config.regime_switch
        assert switch is not None
        above = _benchmark_above_ma(bars, switch.benchmark, switch.ma_period, switch.kind)
        if not above:
            return switch.chop
        sessions = switch.confirm_momentum_sessions
        if sessions:
            df = bars.get(switch.benchmark)
            if df is None or len(df) <= sessions:
                return switch.chop  # unknowable confirmation -> defensive leg
            close = df["close"].astype(float)
            past = float(close.iloc[-1 - sessions])
            if past <= 0 or float(close.iloc[-1]) / past - 1.0 <= switch.confirm_min_return:
                return switch.chop
        return switch.trend

    def _active_engine(self, bars: Mapping[str, DataFrame]) -> DefaultAnalysisEngine:
        """The engine that scores today: self, or the regime-switch leg picked by the
        benchmark trend."""
        leg = self.active_leg(bars)
        if leg is None:
            return self
        switch = self._config.regime_switch
        assert switch is not None
        return self._sub_engines[0] if leg == switch.trend else self._sub_engines[1]  # type: ignore[index]

    def score_universe(
        self,
        bars: Mapping[str, DataFrame],
        asof: dt.datetime,
        extra_signals: Mapping[str, Mapping[str, float]] | None = None,
        regime_score: float | None = None,
    ) -> tuple[list[IndicatorResult], list[SymbolScore]]:
        """Compute indicators and composite scores for the whole universe in one pass,
        applying cross-sectional rank-normalization (P7) when the config enables it.
        Both ``run_analysis`` and ``execute_paper_trades`` go through this so the two
        paths can never diverge; with ``rank_normalize`` off it equals per-symbol scoring.

        ``extra_signals`` (``{symbol: {signal_id: value}}``) feeds non-bar signals
        (fundamentals, news) into the composite — only ids this version *weights* are
        merged, so versions without those weights are byte-for-byte unchanged.
        ``regime_score`` drives the P11 regime multiplier when the version enables it.
        The returned indicator list contains only bar-derived signals — extras are
        persisted by their own producers (observation mode), never double-written."""
        active = self._active_engine(bars)
        if active is not self:
            return active.score_universe(
                bars, asof, extra_signals=extra_signals, regime_score=regime_score
            )
        per_symbol = {
            symbol: self._symbol_indicators(symbol, frame, asof)
            for symbol, frame in bars.items()
        }
        bar_counts = {symbol: len(results) for symbol, results in per_symbol.items()}
        extra_ids = self.weighted_extra_ids()
        if extra_signals and extra_ids:
            for symbol, results in per_symbol.items():
                extras = extra_signals.get(symbol)
                if not extras:
                    continue
                results.extend(
                    IndicatorResult(
                        symbol=symbol,
                        ts=asof,
                        signal_id=signal_id,
                        value=Decimal(str(round(float(value), 8))),
                    )
                    for signal_id, value in extras.items()
                    if signal_id in extra_ids
                )
        if self._config.scoring.rank_normalize:
            per_symbol = rank_normalize_results(per_symbol, self._rank_normalize_targets())
        multiplier = self._regime_multiplier(regime_score)
        market_ok = self._market_uptrend(bars)
        indicators: list[IndicatorResult] = []
        scores: list[SymbolScore] = []
        for symbol, results in per_symbol.items():
            indicators.extend(results[: bar_counts[symbol]])
            score = self._scorer.score(symbol, results, asof, multiplier=multiplier)
            # "Wait for a good moment": in a market downtrend, suppress NEW entries
            # (BUY -> HOLD) while still allowing exits. Governs the first run too.
            if not market_ok and score.action is SignalAction.BUY:
                score = score.model_copy(
                    update={
                        "action": SignalAction.HOLD,
                        "reason": (score.reason or "") + " | market filter: downtrend",
                    }
                )
            scores.append(score)
        return indicators, scores

    def score_symbol(
        self, symbol: str, bars: DataFrame, asof: dt.datetime
    ) -> SymbolScore:
        indicators = self._symbol_indicators(symbol, bars, asof)
        return self._scorer.score(symbol, indicators, asof)

    def rank_symbols(self, scores: list[SymbolScore]) -> list[RankedSymbol]:
        return self._ranker.rank(scores)
