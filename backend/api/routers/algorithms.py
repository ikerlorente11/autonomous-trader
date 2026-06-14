from __future__ import annotations

import datetime as dt
import math

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.performance.metrics import signal_accuracy
from backend.api.deps import get_session
from backend.api.schemas import (
    ExperimentEntry,
    PortfolioComparisonView,
    PortfolioStatsView,
    SignalAccuracySummary,
    SignalEntry,
    SignificanceView,
)
from backend.db.queries.portfolio_queries import (
    get_latest_analysis_ts,
    get_settled_signals,
    get_top_ranked_signals,
)
from backend.experiments.comparator import (
    ExperimentComparator,
    PortfolioComparator,
    PortfolioStats,
    SignificanceResult,
)

router = APIRouter(prefix="/api/algorithms", tags=["algorithms"])


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _stats_view(s: PortfolioStats) -> PortfolioStatsView:
    return PortfolioStatsView(
        portfolio_id=s.portfolio_id,
        name=s.name,
        strategy_label=s.strategy_label,
        n_days=s.n_days,
        total_return=_finite(s.total_return),
        cagr=_finite(s.cagr),
        sharpe=_finite(s.sharpe),
        max_drawdown=_finite(s.max_drawdown),
        pnl_pct=_finite(s.pnl_pct),
        final_nav=_finite(s.final_nav),
        contributed=s.contributed,
    )


def _sig_view(s: SignificanceResult) -> SignificanceView:
    return SignificanceView(
        p_value=_finite(s.p_value),
        statistic=_finite(s.statistic),
        ci_low=_finite(s.ci_low),
        ci_high=_finite(s.ci_high),
        significant=s.significant,
    )


@router.get("/compare", response_model=PortfolioComparisonView)
async def compare_portfolios(
    a: int = Query(..., description="portfolio id A"),
    b: int = Query(..., description="portfolio id B"),
    alpha: float = Query(default=0.05, gt=0.0, lt=0.5),
    session: AsyncSession = Depends(get_session),
) -> PortfolioComparisonView:
    """Statistical A/B of two portfolios over their overlapping NAV history: bootstrap
    on daily-return means + Jobson-Korkie on Sharpe, with a power-gated verdict."""
    if a == b:
        raise HTTPException(status_code=400, detail="pick two distinct portfolios")
    result = await PortfolioComparator(session).compare_portfolios(a, b, alpha=alpha)
    if result is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return PortfolioComparisonView(
        a=_stats_view(result.a),
        b=_stats_view(result.b),
        paired_days=result.paired_days,
        returns_significance=_sig_view(result.returns_significance),
        sharpe_significance=_sig_view(result.sharpe_significance),
        verdict=result.verdict.value,
        notes=result.notes,
    )


@router.get("/signals", response_model=list[SignalEntry])
async def algorithm_signals(
    asof: dt.datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[SignalEntry]:
    asof = asof or await get_latest_analysis_ts(session)
    if asof is None:
        return []
    rows = await get_top_ranked_signals(session, asof, limit=limit)
    return [
        SignalEntry(
            symbol=r.symbol,
            ts=r.ts,
            score=r.score,
            action=r.action,
            reason=r.reason,
            indicator_snapshot=r.indicator_snapshot,
            strategy_version=r.strategy_version,
        )
        for r in rows
    ]


@router.get("/accuracy", response_model=SignalAccuracySummary)
async def algorithm_accuracy(
    session: AsyncSession = Depends(get_session),
) -> SignalAccuracySummary:
    """Hit rate of settled buy signals (forward-return evaluated). Market-wide, not
    per-portfolio — signals are universe-level."""
    rows = await get_settled_signals(session)
    frame = pd.DataFrame(
        {
            "action": [r.action for r in rows],
            "outcome": [r.outcome for r in rows],
            "realized_return": [
                float(r.realized_return) if r.realized_return is not None else float("nan")
                for r in rows
            ],
        }
    )
    result = signal_accuracy(frame)
    accuracy = result.accuracy
    return SignalAccuracySummary(
        accuracy=accuracy if accuracy is not None and math.isfinite(accuracy) else None,
        signal_count=result.signal_count,
        correct_count=result.correct_count,
    )


@router.get("/experiments", response_model=list[ExperimentEntry])
async def algorithm_experiments(
    session: AsyncSession = Depends(get_session),
) -> list[ExperimentEntry]:
    comparator = ExperimentComparator(session)
    runs = await comparator.list_runs()
    return [
        ExperimentEntry(
            id=r.id,
            strategy_version=r.strategy_version,
            started_at=r.started_at,
            ended_at=r.ended_at,
            config=r.config,
            notes=r.notes,
        )
        for r in runs
    ]
