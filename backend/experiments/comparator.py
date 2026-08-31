from __future__ import annotations

import datetime as dt
import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.performance import metrics
from backend.db.models import ExperimentRun
from backend.db.queries.portfolio_queries import (
    compute_contributed_capital,
    get_nav_history,
    get_portfolio,
)

# Minimum paired sessions before a verdict is anything but INSUFFICIENT_EVIDENCE —
# below this there is no statistical power (diagnostics: "≥20 sesiones por brazo").
_MIN_PAIRED_DAYS = 20

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


@dataclass(frozen=True)
class PortfolioStats:
    portfolio_id: int
    name: str
    strategy_label: str | None
    n_days: int
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    final_nav: float
    contributed: float

    @property
    def pnl_pct(self) -> float:
        """Return on contributed capital — the live A/B metric (vs net deposits)."""
        if self.contributed <= 0:
            return float("nan")
        return self.final_nav / self.contributed - 1.0


@dataclass(frozen=True)
class LeaderboardEntry:
    portfolio_id: int
    name: str
    strategy_label: str | None
    kind: str
    active: bool
    total_return: float
    benchmark_return: float
    excess: float
    sharpe: float
    max_drawdown: float


@dataclass(frozen=True)
class Leaderboard:
    """Every arm measured over the SAME sessions.

    Portfolios were created on different dates (v1/v3 from 15-jun, v7/v8 from 22-jul,
    v10 from 31-jul), so their since-inception numbers answer different questions and
    ranking them against each other is meaningless. This intersects the NAV dates and
    reports only that window."""

    start: dt.date | None
    end: dt.date | None
    sessions: int
    entries: list[LeaderboardEntry]
    excluded: list[str]


@dataclass(frozen=True)
class PortfolioComparison:
    a: PortfolioStats
    b: PortfolioStats
    paired_days: int
    returns_significance: SignificanceResult
    sharpe_significance: SignificanceResult
    verdict: ComparisonVerdict
    notes: list[str] = field(default_factory=list)


class PortfolioComparator(ExperimentComparator):
    """Statistical A/B of two live portfolios over their overlapping NAV history.

    Reuses the significance machinery (bootstrap on daily-return means, Jobson-Korkie
    on Sharpe) but feeds it the real ``portfolio_nav`` series, since the live pipeline
    compares by portfolio (each runs a strategy version), not by ``experiment_runs``.
    """

    async def _nav_frame(self, portfolio_id: int) -> pd.DataFrame:
        far_past = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        far_future = dt.datetime(2100, 1, 1, tzinfo=dt.timezone.utc)
        rows = await get_nav_history(self._session, portfolio_id, far_past, far_future)
        return pd.DataFrame(
            {"ts": [r.ts for r in rows], "total": [float(r.total) for r in rows]}
        )

    async def _stats(self, portfolio_id: int) -> PortfolioStats | None:
        portfolio = await get_portfolio(self._session, portfolio_id)
        if portfolio is None:
            return None
        nav = await self._nav_frame(portfolio_id)
        series = metrics._nav_series(nav)
        contributed = float(await compute_contributed_capital(self._session, portfolio_id))
        return PortfolioStats(
            portfolio_id=portfolio_id,
            name=portfolio.name,
            strategy_label=portfolio.strategy_label,
            n_days=int(len(series)),
            total_return=metrics.total_return(nav).pct,
            cagr=metrics.cagr(nav),
            sharpe=metrics.sharpe_ratio(nav),
            max_drawdown=metrics.max_drawdown(nav).max_drawdown,
            final_nav=float(series.iloc[-1]) if len(series) else float("nan"),
            contributed=contributed,
        )

    async def _paired_returns(
        self, a_id: int, b_id: int
    ) -> tuple[list[float], list[float]]:
        """Daily returns of both portfolios aligned on their common session dates —
        the Sharpe (Jobson-Korkie) test needs paired, equal-length series."""
        ra = metrics.daily_returns(await self._nav_frame(a_id))
        rb = metrics.daily_returns(await self._nav_frame(b_id))
        ra.index = pd.to_datetime(ra.index).normalize()
        rb.index = pd.to_datetime(rb.index).normalize()
        common = ra.index.intersection(rb.index)
        return [float(x) for x in ra.loc[common]], [float(x) for x in rb.loc[common]]

    async def compare_portfolios(
        self, a_id: int, b_id: int, alpha: float = 0.05
    ) -> PortfolioComparison | None:
        stats_a = await self._stats(a_id)
        stats_b = await self._stats(b_id)
        if stats_a is None or stats_b is None:
            return None

        ret_a, ret_b = await self._paired_returns(a_id, b_id)
        paired = len(ret_a)
        notes: list[str] = []

        if paired < _MIN_PAIRED_DAYS:
            notes.append(
                f"only {paired} paired sessions (< {_MIN_PAIRED_DAYS}); not enough power"
            )
            return PortfolioComparison(
                a=stats_a, b=stats_b, paired_days=paired,
                returns_significance=_NAN_SIGNIFICANCE,
                sharpe_significance=_NAN_SIGNIFICANCE,
                verdict=ComparisonVerdict.INSUFFICIENT_EVIDENCE, notes=notes,
            )

        returns_sig = self._significance_returns(ret_a, ret_b, alpha)
        sharpe_sig = self._significance_sharpe(ret_a, ret_b, alpha)

        if returns_sig.significant:
            # statistic = mean(a) - mean(b): positive -> A's daily returns are higher.
            verdict = (
                ComparisonVerdict.A_BETTER
                if returns_sig.statistic > 0
                else ComparisonVerdict.B_BETTER
            )
        else:
            verdict = ComparisonVerdict.NO_SIGNIFICANT_DIFFERENCE

        return PortfolioComparison(
            a=stats_a, b=stats_b, paired_days=paired,
            returns_significance=returns_sig, sharpe_significance=sharpe_sig,
            verdict=verdict, notes=notes,
        )

    async def _nav_bench_frame(self, portfolio_id: int) -> pd.DataFrame:
        far_past = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        far_future = dt.datetime(2100, 1, 1, tzinfo=dt.timezone.utc)
        rows = await get_nav_history(self._session, portfolio_id, far_past, far_future)
        return pd.DataFrame(
            {
                "ts": [r.ts for r in rows],
                "total": [float(r.total) for r in rows],
                "benchmark": [
                    float(r.benchmark_value) if r.benchmark_value is not None else float("nan")
                    for r in rows
                ],
            }
        )

    async def leaderboard(
        self,
        portfolios: Sequence[Any],
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> Leaderboard:
        """Rank every portfolio over the sessions they ALL have in common.

        ``start``/``end`` clip the window further (e.g. "since the reset"); without
        them the window is the natural intersection, which is the youngest arm's
        history. Arms with fewer than 2 sessions in the window are excluded by name
        rather than silently dropped — a truncated leaderboard that looks complete is
        worse than no leaderboard."""
        frames: dict[int, pd.DataFrame] = {}
        for p in portfolios:
            frame = await self._nav_bench_frame(p.id)
            if not frame.empty:
                frame = frame.assign(day=pd.to_datetime(frame["ts"]).dt.normalize())
            frames[p.id] = frame

        common: pd.DatetimeIndex | None = None
        for frame in frames.values():
            if frame.empty:
                continue
            days = pd.DatetimeIndex(frame["day"].unique())
            common = days if common is None else common.intersection(days)
        if common is not None and start is not None:
            common = common[common >= pd.Timestamp(start, tz="UTC")]
        if common is not None and end is not None:
            common = common[common <= pd.Timestamp(end, tz="UTC")]

        entries: list[LeaderboardEntry] = []
        excluded: list[str] = []
        if common is None or len(common) < 2:
            return Leaderboard(
                start=None, end=None, sessions=0, entries=[],
                excluded=[p.name for p in portfolios],
            )

        for p in portfolios:
            frame = frames[p.id]
            window = (
                frame[frame["day"].isin(common)].sort_values("ts")
                if not frame.empty
                else frame
            )
            if len(window) < 2:
                excluded.append(p.name)
                continue
            ret = metrics.total_return(window).pct
            bench = metrics.total_return(window, column="benchmark").pct
            entries.append(
                LeaderboardEntry(
                    portfolio_id=p.id,
                    name=p.name,
                    strategy_label=p.strategy_label,
                    kind=p.kind,
                    active=bool(p.active),
                    total_return=ret,
                    benchmark_return=bench,
                    excess=(ret - bench) if not (math.isnan(ret) or math.isnan(bench)) else float("nan"),
                    sharpe=metrics.sharpe_ratio(window),
                    max_drawdown=metrics.max_drawdown(window).max_drawdown,
                )
            )

        entries.sort(
            key=lambda e: (-e.excess if not math.isnan(e.excess) else float("inf"))
        )
        return Leaderboard(
            start=common.min().date(),
            end=common.max().date(),
            sessions=int(len(common)),
            entries=entries,
            excluded=excluded,
        )
