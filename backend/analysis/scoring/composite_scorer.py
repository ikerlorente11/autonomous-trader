"""Composite scoring: combine per-symbol indicator sub-scores into one 0–100 score.

``CompositeScorer`` is the pure seam (Software Architect): it takes already-computed
``IndicatorResult``s for one symbol and returns a ``SymbolScore`` — no DataFrames, no
DB. ``WeightedCompositeScorer`` is the Phase-4 implementation: a weighted average of
the configured indicators, renormalizing the weights over whichever signals are
actually present (synthesis §3.3 — never impute a missing signal to zero). Persistence
to ``signal_values`` / ``algorithm_signals`` lives in ``scoring.persistence`` (the layer
that holds the DB session), not in this pure unit.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from backend.analysis.config import StrategyConfig
from backend.contracts import IndicatorResult, SignalAction, SymbolScore


@runtime_checkable
class CompositeScorer(Protocol):
    def score(
        self, symbol: str, indicators: Sequence[IndicatorResult], asof: dt.datetime
    ) -> SymbolScore: ...


class WeightedCompositeScorer:
    def __init__(self, config: StrategyConfig) -> None:
        self._config = config
        self._weights = config.scoring.weights
        self._total_weight = sum(self._weights.values())

    def score(
        self, symbol: str, indicators: Sequence[IndicatorResult], asof: dt.datetime
    ) -> SymbolScore:
        snapshot: dict[str, float] = {}
        weighted_sum = 0.0
        present_weight = 0.0
        for ind in indicators:
            value = float(ind.value)
            snapshot[ind.signal_id] = value
            weight = self._weights.get(ind.signal_id)
            if weight is None:
                continue
            weighted_sum += weight * value
            present_weight += weight

        completeness = (
            present_weight / self._total_weight if self._total_weight > 0 else 0.0
        )
        if present_weight > 0:
            raw = weighted_sum / present_weight
        else:
            raw = self._config.scoring.score_min
        score = min(
            self._config.scoring.score_max,
            max(self._config.scoring.score_min, raw),
        )
        if present_weight == 0:
            # No weighted signal present at all: zero information, not a low score.
            # Exiting a held name on *low* coverage is policy; exiting on *no*
            # coverage would liquidate on a data outage. Hold.
            action = SignalAction.HOLD
        elif score >= self._config.ranker.min_score_to_act:
            action = SignalAction.BUY
        elif score <= self._config.ranker.min_score_to_exit:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD
        # Bake the low-coverage gate into the persisted action so it holds wherever the
        # signal is later read (the action is authoritative; the ranker is not always in
        # the path). Only entries are suppressed — a held low-coverage name may still exit.
        if action is SignalAction.BUY and completeness < self._config.ranker.min_data_completeness:
            action = SignalAction.HOLD
        return SymbolScore(
            symbol=symbol,
            ts=asof,
            score=Decimal(str(round(score, 4))),
            action=action,
            reason=f"{len(snapshot)} signals, completeness {completeness:.2f}",
            indicator_snapshot=snapshot,
            data_completeness=Decimal(str(round(completeness, 4))),
        )
