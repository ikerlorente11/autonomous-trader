from __future__ import annotations

import datetime as dt
import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ExperimentRun

# Significance-test parameters. Kept module-level so tests are deterministic and
# the magic numbers live in one named place.
_BOOTSTRAP_ITERATIONS = 10_000
_BOOTSTRAP_SEED = 20240601
_MIN_EXPECTED_COUNT = 5.0  # below this, prefer Fisher's exact over the z-approximation
_NEWTON_MAX_ITER = 100
_NEWTON_TOL = 1e-12


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF via Newton-Raphson on `_norm_cdf` (no scipy dependency)."""
    if not 0.0 < p < 1.0:
        return float("nan")
    x = 0.0
    for _ in range(_NEWTON_MAX_ITER):
        err = _norm_cdf(x) - p
        if abs(err) < _NEWTON_TOL:
            break
        pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
        if pdf < _NEWTON_TOL:
            break
        x -= err / pdf
    return x


def _fisher_exact_two_sided(wins_a: int, n_a: int, wins_b: int, n_b: int) -> float:
    """Two-sided Fisher's exact p-value for a 2x2 table (successes x group).

    Exact hypergeometric tail; computed in log-space to avoid overflow when counts are large.
    """
    if n_a < 0 or n_b < 0 or wins_a < 0 or wins_b < 0:
        return float("nan")
    if wins_a > n_a or wins_b > n_b:
        return float("nan")

    total = n_a + n_b
    successes = wins_a + wins_b
    if total == 0:
        return float("nan")

    def log_comb(n: int, k: int) -> float:
        if k < 0 or k > n:
            return float("-inf")
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)

    log_denom = log_comb(total, n_a)

    def table_prob(x: int) -> float:
        log_p = log_comb(successes, x) + log_comb(total - successes, n_a - x) - log_denom
        # exp() underflows to 0.0 for extremely tiny probabilities; that's acceptable for tail sums.
        return math.exp(log_p)

    observed = table_prob(wins_a)
    lo = max(0, successes - n_b)
    hi = min(successes, n_a)
    tol = observed * (1.0 + 1e-7)

    p_value = 0.0
    for x in range(lo, hi + 1):
        px = table_prob(x)
        if px <= tol:
            p_value += px
    return min(1.0, p_value)


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


_NAN_SIGNIFICANCE = SignificanceResult(
    p_value=float("nan"),
    statistic=float("nan"),
    ci_low=float("nan"),
    ci_high=float("nan"),
    significant=False,
)


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
arrA = np.asarray(a, dtype=float)
arrB = np.asarray(b, dtype=float)
if arrA.size < 2 or arrB.size < 2:
    return _NAN_SIGNIFICANCE
if not np.isfinite(arrA).all() or not np.isfinite(arrB).all():
    return _NAN_SIGNIFICANCE

        observed = float(arrA.mean() - arrB.mean())
        rng = np.random.default_rng(_BOOTSTRAP_SEED)
        bootA = rng.choice(arrA, size=(_BOOTSTRAP_ITERATIONS, arrA.size), replace=True).mean(axis=1)
        bootB = rng.choice(arrB, size=(_BOOTSTRAP_ITERATIONS, arrB.size), replace=True).mean(axis=1)
        bootDiff = bootA - bootB

        pBelow = float(np.mean(bootDiff <= 0.0))
        pAbove = float(np.mean(bootDiff >= 0.0))
        pValue = min(1.0, 2.0 * min(pBelow, pAbove))
        ciLow, ciHigh = np.quantile(bootDiff, [alpha / 2.0, 1.0 - alpha / 2.0])
        return SignificanceResult(
            p_value=pValue,
            statistic=observed,
            ci_low=float(ciLow),
            ci_high=float(ciHigh),
            significant=pValue < alpha,
        )

    def _significance_sharpe(
        self, a: Sequence[float], b: Sequence[float], alpha: float
    ) -> SignificanceResult:
        """Jobson-Korkie / Memmel test for a Sharpe-ratio difference.

        Requires paired, equal-length return series (the correction needs their
        correlation), so mismatched lengths are a caller error, not missing data.
        """
        arrA = np.asarray(a, dtype=float)
        arrB = np.asarray(b, dtype=float)
        if arrA.size != arrB.size:
            raise ValueError("Sharpe significance needs paired equal-length return series")
        n = arrA.size
        if n < 2:
            return _NAN_SIGNIFICANCE

        sdA = arrA.std(ddof=1)
        sdB = arrB.std(ddof=1)
        if sdA == 0 or sdB == 0 or np.isnan(sdA) or np.isnan(sdB):
            return _NAN_SIGNIFICANCE

        sharpeA = float(arrA.mean() / sdA)
        sharpeB = float(arrB.mean() / sdB)
        rho = float(np.corrcoef(arrA, arrB)[0, 1])
        variance = (
            2.0
            - 2.0 * rho
            + 0.5 * (sharpeA**2 + sharpeB**2 - 2.0 * sharpeA * sharpeB * rho**2)
        ) / n
        if variance <= 0:
            return _NAN_SIGNIFICANCE

        diff = sharpeA - sharpeB
        se = math.sqrt(variance)
        zStat = diff / se
        pValue = 2.0 * (1.0 - _norm_cdf(abs(zStat)))
        zCrit = _norm_ppf(1.0 - alpha / 2.0)
        return SignificanceResult(
            p_value=pValue,
            statistic=zStat,
            ci_low=diff - zCrit * se,
            ci_high=diff + zCrit * se,
            significant=pValue < alpha,
        )

    def _significance_proportion(
        self, wins_a: int, n_a: int, wins_b: int, n_b: int, alpha: float
    ) -> SignificanceResult:
        """Two-proportion z-test (Fisher's exact at low counts) for hit/win-rate."""
        if n_a <= 0 or n_b <= 0:
            return _NAN_SIGNIFICANCE

        propA = wins_a / n_a
        propB = wins_b / n_b
        diff = propA - propB

        pooled = (wins_a + wins_b) / (n_a + n_b)
        expected = [
            pooled * n_a,
            (1.0 - pooled) * n_a,
            pooled * n_b,
            (1.0 - pooled) * n_b,
        ]
        if min(expected) < _MIN_EXPECTED_COUNT:
            pValue = _fisher_exact_two_sided(wins_a, n_a, wins_b, n_b)
            return SignificanceResult(
                p_value=pValue,
                statistic=diff,
                ci_low=float("nan"),
                ci_high=float("nan"),
                significant=pValue < alpha,
            )

        sePooled = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
        if sePooled == 0:
            return _NAN_SIGNIFICANCE
        zStat = diff / sePooled
        pValue = 2.0 * (1.0 - _norm_cdf(abs(zStat)))
        seUnpooled = math.sqrt(
            propA * (1.0 - propA) / n_a + propB * (1.0 - propB) / n_b
        )
        zCrit = _norm_ppf(1.0 - alpha / 2.0)
        return SignificanceResult(
            p_value=pValue,
            statistic=zStat,
            ci_low=diff - zCrit * seUnpooled,
            ci_high=diff + zCrit * seUnpooled,
            significant=pValue < alpha,
        )
