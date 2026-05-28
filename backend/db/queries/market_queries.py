from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import MacroSeries, MarketBar, MarketSentiment, SignalValue


async def get_bars_range(
    session: AsyncSession, symbol: str, start: dt.datetime, end: dt.datetime
) -> Sequence[MarketBar]:
    """OHLCV bars for one symbol over a time range (charting / backtest input)."""
    stmt: Select[tuple[MarketBar]] = (
        select(MarketBar)
        .where(
            MarketBar.symbol == symbol,
            MarketBar.ts >= start,
            MarketBar.ts <= end,
        )
        .order_by(MarketBar.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_latest_bars(
    session: AsyncSession, symbols: Sequence[str]
) -> Sequence[MarketBar]:
    """Most recent bar per symbol (portfolio valuation / ranking snapshot)."""
    stmt: Select[tuple[MarketBar]] = (
        select(MarketBar)
        .where(MarketBar.symbol.in_(symbols))
        .distinct(MarketBar.symbol)
        .order_by(MarketBar.symbol, MarketBar.ts.desc())
    )
    return (await session.scalars(stmt)).all()


async def get_signal_series(
    session: AsyncSession,
    symbol: str,
    signal_id: str,
    start: dt.datetime,
    end: dt.datetime,
) -> Sequence[SignalValue]:
    """Time series of one computed signal for one symbol."""
    stmt: Select[tuple[SignalValue]] = (
        select(SignalValue)
        .where(
            SignalValue.symbol == symbol,
            SignalValue.signal_id == signal_id,
            SignalValue.ts >= start,
            SignalValue.ts <= end,
        )
        .order_by(SignalValue.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_latest_signal_snapshot(
    session: AsyncSession, asof_date: dt.datetime
) -> Sequence[SignalValue]:
    """All signal values across the universe at a given timestamp (scorer input)."""
    stmt: Select[tuple[SignalValue]] = (
        select(SignalValue)
        .where(SignalValue.ts == asof_date)
        .order_by(SignalValue.symbol, SignalValue.signal_id)
    )
    return (await session.scalars(stmt)).all()


async def get_market_sentiment(
    session: AsyncSession, asof: dt.datetime
) -> MarketSentiment | None:
    """Most recent market-wide sentiment row at or before ``asof``."""
    stmt: Select[tuple[MarketSentiment]] = (
        select(MarketSentiment)
        .where(MarketSentiment.ts <= asof)
        .order_by(MarketSentiment.ts.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_macro_regime_inputs(
    session: AsyncSession, series_ids: Sequence[str]
) -> Sequence[MacroSeries]:
    """Latest value per requested macro series (regime classifier input)."""
    stmt: Select[tuple[MacroSeries]] = (
        select(MacroSeries)
        .where(MacroSeries.series_id.in_(series_ids))
        .distinct(MacroSeries.series_id)
        .order_by(MacroSeries.series_id, MacroSeries.ts.desc())
    )
    return (await session.scalars(stmt)).all()
