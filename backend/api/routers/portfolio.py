from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.performance.metrics import (
    build_round_trips,
    risk_free_rate_from_env,
    summarize_performance,
)
from backend.api.deps import get_session
from backend.api.schemas import PortfolioSummary
from backend.contracts import PerformanceMetrics, Position, PortfolioSnapshot
from backend.db.queries.market_queries import get_latest_bars
from backend.db.queries.portfolio_queries import (
    compute_cash_from_ledger,
    get_filled_orders,
    get_nav_history,
    get_open_positions,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_DEFAULT_STARTING_CASH = Decimal("100000")


def _starting_cash() -> Decimal:
    raw = os.environ.get("STARTING_CASH")
    if raw is None or raw.strip() == "":
        return _DEFAULT_STARTING_CASH
    return Decimal(raw)


@router.get("/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    session: AsyncSession = Depends(get_session),
) -> PortfolioSummary:
    starting = _starting_cash()
    cash = await compute_cash_from_ledger(session, starting)
    positions = await get_open_positions(session)
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
        cash=cash,
        equity=equity,
        total=total,
        starting_cash=starting,
        total_pnl=total - starting,
        unrealized_pnl=unrealized,
        positions_count=len(positions),
    )


@router.get("/positions", response_model=list[Position])
async def portfolio_positions(
    session: AsyncSession = Depends(get_session),
) -> list[Position]:
    rows = await get_open_positions(session)
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
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSnapshot]:
    end = end or dt.datetime.now(dt.timezone.utc)
    start = start or (end - dt.timedelta(days=90))
    rows = await get_nav_history(session, start, end)
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
    session: AsyncSession = Depends(get_session),
) -> PerformanceMetrics:
    end = end or dt.datetime.now(dt.timezone.utc)
    start = start or (end - dt.timedelta(days=365))
    nav_rows = await get_nav_history(session, start, end)
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
    orders = await get_filled_orders(session)
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
