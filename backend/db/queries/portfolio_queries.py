from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AlgorithmSignal,
    PortfolioNav,
    PortfolioPosition,
    TradeOrder,
    Watchlist,
)


async def get_open_positions(session: AsyncSession) -> Sequence[PortfolioPosition]:
    """Current non-zero positions with unrealized P&L."""
    stmt: Select[tuple[PortfolioPosition]] = (
        select(PortfolioPosition)
        .where(PortfolioPosition.qty != 0)
        .order_by(PortfolioPosition.symbol)
    )
    return (await session.scalars(stmt)).all()


async def get_nav_history(
    session: AsyncSession, start: dt.datetime, end: dt.datetime
) -> Sequence[PortfolioNav]:
    """Portfolio NAV (and benchmark) over a time range for the equity curve."""
    stmt: Select[tuple[PortfolioNav]] = (
        select(PortfolioNav)
        .where(PortfolioNav.ts >= start, PortfolioNav.ts <= end)
        .order_by(PortfolioNav.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_recent_orders(
    session: AsyncSession, limit: int = 50
) -> Sequence[TradeOrder]:
    """Most recent trade orders for the trades table."""
    stmt: Select[tuple[TradeOrder]] = (
        select(TradeOrder).order_by(TradeOrder.ts.desc()).limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_filtered_orders(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int = 50,
) -> Sequence[TradeOrder]:
    """Trade orders with optional symbol / date-range filters (trades table)."""
    stmt: Select[tuple[TradeOrder]] = select(TradeOrder)
    if symbol is not None:
        stmt = stmt.where(TradeOrder.symbol == symbol)
    if start is not None:
        stmt = stmt.where(TradeOrder.ts >= start)
    if end is not None:
        stmt = stmt.where(TradeOrder.ts <= end)
    stmt = stmt.order_by(TradeOrder.ts.desc()).limit(limit)
    return (await session.scalars(stmt)).all()


async def get_filled_orders(session: AsyncSession) -> Sequence[TradeOrder]:
    """All filled orders ascending — the closed-trip / round-trip ledger input."""
    stmt: Select[tuple[TradeOrder]] = (
        select(TradeOrder)
        .where(func.lower(TradeOrder.status) == "filled")
        .order_by(TradeOrder.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_position(
    session: AsyncSession, symbol: str
) -> PortfolioPosition | None:
    """Single position row by symbol (broker upsert read)."""
    return await session.get(PortfolioPosition, symbol)


async def compute_cash_from_ledger(
    session: AsyncSession, starting_cash: Decimal
) -> Decimal:
    """Cash = starting cash − Σ(buy price·qty) + Σ(sell price·qty) over filled orders.

    Cash is a pure function of the append-only order ledger, so it never needs a
    mutable cash row and is reconstructable after any restart.
    """
    flow = func.coalesce(
        func.sum(
            case(
                (func.lower(TradeOrder.side) == "buy", TradeOrder.price * TradeOrder.qty),
                else_=-(TradeOrder.price * TradeOrder.qty),
            )
        ),
        0,
    )
    stmt = select(flow).where(func.lower(TradeOrder.status) == "filled")
    spent = (await session.scalar(stmt)) or Decimal(0)
    return starting_cash - Decimal(spent)


async def count_orders_since(
    session: AsyncSession, since: dt.datetime
) -> int:
    """How many orders were written at/after ``since`` (day-level idempotency guard)."""
    stmt = select(func.count()).select_from(TradeOrder).where(TradeOrder.ts >= since)
    return int((await session.scalar(stmt)) or 0)


async def get_latest_nav(session: AsyncSession) -> PortfolioNav | None:
    """Most recent NAV snapshot, if any."""
    stmt = select(PortfolioNav).order_by(PortfolioNav.ts.desc()).limit(1)
    return (await session.scalars(stmt)).one_or_none()


async def get_top_ranked_signals(
    session: AsyncSession, asof_date: dt.datetime, limit: int = 20
) -> Sequence[AlgorithmSignal]:
    """Highest-scoring algorithm signals at a given timestamp (buy candidates)."""
    stmt: Select[tuple[AlgorithmSignal]] = (
        select(AlgorithmSignal)
        .where(AlgorithmSignal.ts == asof_date)
        .order_by(AlgorithmSignal.score.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_latest_analysis_ts(session: AsyncSession) -> dt.datetime | None:
    """Timestamp of the most recent analysis run (max algorithm_signals.ts)."""
    stmt = select(func.max(AlgorithmSignal.ts))
    return await session.scalar(stmt)


async def get_active_watchlist(session: AsyncSession) -> Sequence[Watchlist]:
    """Active watchlist symbols with sector / asset-class metadata."""
    stmt: Select[tuple[Watchlist]] = (
        select(Watchlist)
        .where(Watchlist.active.is_(True))
        .order_by(Watchlist.symbol)
    )
    return (await session.scalars(stmt)).all()
