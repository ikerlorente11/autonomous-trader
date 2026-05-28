from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ExperimentRun


class ComparisonVerdict(str, enum.Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_SIGNIFICANT_DIFFERENCE = "NO_SIGNIFICANT_DIFFERENCE"
    A_BETTER = "A_BETTER"
    B_BETTER = "B_BETTER"


@dataclass(frozen=True)
class ExperimentSummary:
    """Frozen per-run metrics — mirrors FP&A `summary.json` (reporting-structure.md §5.3)."""

    strategy_version: str
    period_start: dt.date
    period_end: dt.date
    returns: dict[str, float]
    risk: dict[str, float]
    activity: dict[str, float]
    signal_quality: dict[str, float]
    regime_mix: dict[str, float]


@dataclass(frozen=True)
class SignificanceResult:
    p_value: float
    statistic: float
    ci_low: float
    ci_high: float
    significant: bool


@dataclass(frozen=True)
class MetricDelta:
    key: str
    a: float
    b: float
    delta: float
    pct: float
    significance: SignificanceResult | None = None


@dataclass(frozen=True)
class ComparisonResult:
    a: ExperimentSummary
    b: ExperimentSummary
    metric_deltas: list[MetricDelta]
    equity_curves: dict[str, list[dict[str, Any]]]
    verdict: ComparisonVerdict
    notes: list[str] = field(default_factory=list)


class ExperimentComparator:
    """Loads run summaries, computes deltas with significance, emits chart-ready payloads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_runs(self) -> Sequence[ExperimentRun]:
        """All experiment runs, most recent first, for the comparison picker."""
        stmt = select(ExperimentRun).order_by(ExperimentRun.started_at.desc())
        return (await self._session.scalars(stmt)).all()

    async def load_summary(self, run_id: int) -> ExperimentSummary:
        """Frozen `results` if present (schema §5); else compute from version-tagged rows."""
        raise NotImplementedError

    async def daily_returns(self, run_id: int) -> Sequence[tuple[dt.date, Decimal]]:
        """NAV-derived daily return series over the run window, for tests and rebased curves."""
        raise NotImplementedError

    async def compare(self, run_a_id: int, run_b_id: int) -> ComparisonResult:
        """Full A-vs-B comparison: deltas, significance, regime-aware verdict, chart payload."""
        raise NotImplementedError

    def _significance_returns(
        self, a: Sequence[float], b: Sequence[float], alpha: float
    ) -> SignificanceResult:
        """Bootstrap test on daily-return means (non-normal, small-n safe)."""
        raise NotImplementedError

    def _significance_sharpe(
        self, a: Sequence[float], b: Sequence[float], alpha: float
    ) -> SignificanceResult:
        """Jobson-Korkie / Memmel test for a Sharpe-ratio difference."""
        raise NotImplementedError

    def _significance_proportion(
        self, wins_a: int, n_a: int, wins_b: int, n_b: int, alpha: float
    ) -> SignificanceResult:
        """Two-proportion z-test (Fisher's exact at low counts) for hit/win-rate."""
        raise NotImplementedError
