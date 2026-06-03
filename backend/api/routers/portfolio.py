from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.performance.metrics import (
    FPA_PERIODS,
    PeriodPnl,
    attribution_by_sector,
    attribution_by_symbol,
    build_round_trips,
    period_pnl,
    period_start,
    risk_free_rate_from_env,
    summarize_performance,
)
from backend.api.deps import get_session, resolve_portfolio
from backend.api.schemas import PortfolioSummary
from backend.contracts import (
    AttributionReport,
    PerformanceMetrics,
    PeriodPerformance,
    Position,
    PortfolioSnapshot,
    SectorAttributionItem,
    SymbolAttributionItem,
)
from backend.db.models import PortfolioNav, TradeOrder
from backend.db.queries.market_queries import get_latest_bars
from backend.db.queries.portfolio_queries import (
    compute_cash,
    compute_contributed_capital,
    get_active_watchlist,
    get_filled_orders,
    get_nav_history,
    get_open_positions,
    get_portfolio,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _finite_or_none(value: float) -> float | None:
    """Map NaN/inf to None so the response is valid JSON (null, not the NaN token)."""
    return value if math.isfinite(value) else None


def _nav_frame(rows: Sequence[PortfolioNav]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ts": [r.ts for r in rows], "total": [float(r.total) for r in rows]}
    )


def _orders_frame(orders: Sequence[TradeOrder]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [o.symbol for o in orders],
            "side": [o.side for o in orders],
            "qty": [float(o.qty) for o in orders],
            "price": [
                float(o.price) if o.price is not None else float("nan") for o in orders
            ],
            "ts": [o.ts for o in orders],
            "status": [o.status for o in orders],
        }
    )


async def _unrealized_marks(
    session: AsyncSession, portfolio_id: int
) -> dict[str, float]:
    """Current open-position unrealized P&L per symbol, marked on the latest close
    (falling back to avg_cost), mirroring the /summary equity computation."""
    positions = await get_open_positions(session, portfolio_id)
    if not positions:
        return {}
    prices: dict[str, Decimal] = {
        bar.symbol: bar.close
        for bar in await get_latest_bars(session, [p.symbol for p in positions])
    }
    return {
        p.symbol: float((prices.get(p.symbol, p.avg_cost) - p.avg_cost) * p.qty)
        for p in positions
    }


def _period_dto(p: PeriodPnl) -> PeriodPerformance:
    return PeriodPerformance(
        period=p.period,
        start_ts=p.start_ts.to_pydatetime() if p.start_ts is not None else None,
        end_ts=p.end_ts.to_pydatetime() if p.end_ts is not None else None,
        start_value=p.start_value,
        end_value=p.end_value,
        pnl=p.pnl,
        return_pct=_finite_or_none(p.return_pct),
    )


@router.get("/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> PortfolioSummary:
    portfolio = await get_portfolio(session, portfolio_id)
    cash = await compute_cash(session, portfolio_id)
    contributed = await compute_contributed_capital(session, portfolio_id)
    positions = await get_open_positions(session, portfolio_id)
    prices: dict[str, Decimal] = {}
    if positions:
        for bar in await get_latest_bars(session, [p.symbol for p in positions]):
            prices[bar.symbol] = bar.close
    equity = sum(
        (p.qty * prices.get(p.symbol, p.avg_cost) for p in positions), Decimal(0)
    )
    unrealized = sum(
        (
            (prices.get(p.symbol, p.avg_cost) - p.avg_cost) * p.qty
            for p in positions
        ),
        Decimal(0),
    )
    total = cash + equity
    return PortfolioSummary(
        portfolio_id=portfolio_id,
        name=portfolio.name if portfolio else "",
        cash=cash,
        equity=equity,
        total=total,
        contributed_capital=contributed,
        total_pnl=total - contributed,
        unrealized_pnl=unrealized,
        positions_count=len(positions),
    )


@router.get("/positions", response_model=list[Position])
async def portfolio_positions(
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> list[Position]:
    rows = await get_open_positions(session, portfolio_id)
    return [
        Position(
            symbol=r.symbol,
            qty=r.qty,
            avg_cost=r.avg_cost,
            current_price=r.current_price,
            unrealized_pnl=r.unrealized_pnl,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/nav", response_model=list[PortfolioSnapshot])
async def portfolio_nav(
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSnapshot]:
    end = end or dt.datetime.now(dt.timezone.utc)
    start = start or (end - dt.timedelta(days=90))
    rows = await get_nav_history(session, portfolio_id, start, end)
    return [
        PortfolioSnapshot(
            ts=r.ts,
            cash=r.cash,
            equity=r.equity,
            total=r.total,
            benchmark_value=r.benchmark_value,
        )
        for r in rows
    ]


@router.get("/performance", response_model=PerformanceMetrics)
async def portfolio_performance(
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> PerformanceMetrics:
    end = end or dt.datetime.now(dt.timezone.utc)
    start = start or (end - dt.timedelta(days=365))
    nav_rows = await get_nav_history(session, portfolio_id, start, end)
    if len(nav_rows) < 2:
        return PerformanceMetrics()
    nav_df = pd.DataFrame(
        {
            "ts": [r.ts for r in nav_rows],
            "total": [float(r.total) for r in nav_rows],
            "benchmark_value": [
                float(r.benchmark_value) if r.benchmark_value is not None else float("nan")
                for r in nav_rows
            ],
        }
    )
    orders = await get_filled_orders(session, portfolio_id)
    orders_df = pd.DataFrame(
        {
            "symbol": [o.symbol for o in orders],
            "side": [o.side for o in orders],
            "qty": [float(o.qty) for o in orders],
            "price": [float(o.price) if o.price is not None else float("nan") for o in orders],
            "ts": [o.ts for o in orders],
            "status": [o.status for o in orders],
        }
    )
    trips = build_round_trips(orders_df)
    bundle = summarize_performance(nav_df, trips, risk_free_rate_from_env())
    return PerformanceMetrics(**bundle)


@router.get("/performance/periods", response_model=list[PeriodPerformance])
async def portfolio_performance_periods(
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> list[PeriodPerformance]:
    now = dt.datetime.now(dt.timezone.utc)
    nav_rows = await get_nav_history(session, portfolio_id, _EPOCH, now)
    nav_df = _nav_frame(nav_rows)
    return [_period_dto(period_pnl(nav_df, period, now)) for period in FPA_PERIODS]


@router.get("/attribution", response_model=AttributionReport)
async def portfolio_attribution(
    period: Literal["wtd", "mtd", "ytd", "inception"] = Query(default="mtd"),
    by: Literal["symbol", "sector"] = Query(default="symbol"),
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> AttributionReport:
    now = dt.datetime.now(dt.timezone.utc)
    window_start = period_start(now, period)
    orders = await get_filled_orders(session, portfolio_id)
    trips = build_round_trips(_orders_frame(orders))
    unrealized = await _unrealized_marks(session, portfolio_id)
    symbol_attr = attribution_by_symbol(
        trips, unrealized, start=window_start, end=now
    )
    total_pnl = sum(a.total_pnl for a in symbol_attr)

    if by == "sector":
        sector_map = {
            w.symbol: w.sector
            for w in await get_active_watchlist(session)
            if w.sector is not None
        }
        sectors = [
            SectorAttributionItem(
                sector=a.sector,
                realized_pnl=a.realized_pnl,
                unrealized_pnl=a.unrealized_pnl,
                total_pnl=a.total_pnl,
                contribution_pct=_finite_or_none(a.contribution_pct),
            )
            for a in attribution_by_sector(symbol_attr, sector_map)
        ]
        return AttributionReport(
            period=period, axis="sector", total_pnl=total_pnl, sectors=sectors
        )

    symbols = [
        SymbolAttributionItem(
            symbol=a.symbol,
            realized_pnl=a.realized_pnl,
            unrealized_pnl=a.unrealized_pnl,
            total_pnl=a.total_pnl,
            contribution_pct=_finite_or_none(a.contribution_pct),
        )
        for a in symbol_attr
    ]
    return AttributionReport(
        period=period, axis="symbol", total_pnl=total_pnl, symbols=symbols
    )
