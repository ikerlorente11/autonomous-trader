"""Symbol ranking: order scored symbols into the buy-candidate list.

``SymbolRanker`` is the seam (Software Architect); ``ScoreRanker`` is the Phase-4
implementation. Insufficient-data symbols (< an indicator's ``required_periods``) never
produce a ``SymbolScore`` upstream in the engine, so they simply do not reach the
ranker. The ranker drops the rest by config: symbols flagged suspicious by data
validation (``exclude``), below ``min_score_to_act``, or below ``min_data_completeness``
(low coverage). Remaining symbols are ranked by score, highest first. Cutoffs are
config, never code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from backend.analysis.config import StrategyConfig
from backend.contracts import RankedSymbol, SymbolScore


@runtime_checkable
class SymbolRanker(Protocol):
    def rank(self, scores: Sequence[SymbolScore]) -> list[RankedSymbol]: ...


class ScoreRanker:
    def __init__(self, config: StrategyConfig) -> None:
        self._min_score = config.ranker.min_score_to_act
        self._min_completeness = config.ranker.min_data_completeness

    def rank(
        self,
        scores: Sequence[SymbolScore],
        *,
        exclude: frozenset[str] = frozenset(),
    ) -> list[RankedSymbol]:
        eligible = [
            s
            for s in scores
            if s.symbol not in exclude
            and float(s.score) >= self._min_score
            and (s.data_completeness is None or float(s.data_completeness) >= self._min_completeness)
        ]
        eligible.sort(
            key=lambda s: (s.score, s.data_completeness or 0, s.symbol), reverse=True
        )
        return [RankedSymbol(rank=i, score=s) for i, s in enumerate(eligible, start=1)]
