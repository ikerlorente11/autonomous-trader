from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.db.models import (
    IntradayBar,
    MacroSeries,
    MarketBar,
    MarketSentiment,
    SignalValue,
)


async def count_bars_per_symbol(
    session: AsyncSession, symbols: Sequence[str], start: dt.datetime, end: dt.datetime
) -> dict[str, int]:
    """Stored-bar count per symbol within a window (history-sufficiency check)."""
    stmt = (
        select(MarketBar.symbol, func.count())
        .where(
            MarketBar.symbol.in_(symbols),
            MarketBar.ts >= start,
            MarketBar.ts <= end,
        )
        .group_by(MarketBar.symbol)
    )
    return {symbol: count for symbol, count in (await session.execute(stmt)).all()}


async def avg_dollar_volume(
    session: AsyncSession,
    symbols: Sequence[str],
    start: dt.datetime,
    end: dt.datetime,
) -> dict[str, float]:
    """Average daily dollar-volume (avg of close×volume) per symbol over a window.

    The liquidity proxy the microtrading universe is ranked by — day-tradeable names
    are the liquid, tight-spread ones. Symbols with no bars in the window are absent."""
    stmt = (
        select(MarketBar.symbol, func.avg(MarketBar.close * MarketBar.volume))
        .where(
            MarketBar.symbol.in_(symbols),
            MarketBar.ts >= start,
            MarketBar.ts <= end,
        )
        .group_by(MarketBar.symbol)
    )
    return {symbol: float(value) for symbol, value in (await session.execute(stmt)).all()}


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


async def get_close_asof(
    session: AsyncSession, symbol: str, asof: dt.datetime
) -> MarketBar | None:
    """Most recent bar for ``symbol`` at or before ``asof`` (benchmark valuation)."""
    stmt: Select[tuple[MarketBar]] = (
        select(MarketBar)
        .where(MarketBar.symbol == symbol, MarketBar.ts <= asof)
        .order_by(MarketBar.ts.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_close_after(
    session: AsyncSession, symbol: str, asof: dt.datetime
) -> MarketBar | None:
    """First bar for ``symbol`` at or after ``asof`` (signal forward-return horizon)."""
    stmt: Select[tuple[MarketBar]] = (
        select(MarketBar)
        .where(MarketBar.symbol == symbol, MarketBar.ts >= asof)
        .order_by(MarketBar.ts)
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_latest_bars(
    session: AsyncSession, symbols: Sequence[str]
) -> Sequence[MarketBar]:
    """Most recent bar per symbol (portfolio valuation / ranking snapshot).

    Deliberately a window function, NOT ``DISTINCT ON``: TimescaleDB 2.27's SkipScan
    can return WRONG rows for multi-symbol ``DISTINCT ON (symbol) … ORDER BY ts DESC``
    over a hypertable (value-set dependent; live incident 2026-07-22 — v7 sized and
    marked positions at July-6 closes). row_number() never plans through SkipScan."""
    rn = (
        func.row_number()
        .over(partition_by=MarketBar.symbol, order_by=MarketBar.ts.desc())
        .label("rn")
    )
    ranked = (
        select(MarketBar, rn).where(MarketBar.symbol.in_(symbols)).subquery()
    )
    latest = aliased(MarketBar, ranked)
    stmt: Select[tuple[MarketBar]] = select(latest).where(ranked.c.rn == 1)
    return (await session.scalars(stmt)).all()


async def get_intraday_bars_range(
    session: AsyncSession, symbol: str, start: dt.datetime, end: dt.datetime
) -> Sequence[IntradayBar]:
    """Intraday OHLCV bars for one symbol over a time range (micro scoring input)."""
    stmt: Select[tuple[IntradayBar]] = (
        select(IntradayBar)
        .where(
            IntradayBar.symbol == symbol,
            IntradayBar.ts >= start,
            IntradayBar.ts <= end,
        )
        .order_by(IntradayBar.ts)
    )
    return (await session.scalars(stmt)).all()


async def get_latest_intraday_bars(
    session: AsyncSession, symbols: Sequence[str]
) -> Sequence[IntradayBar]:
    """Most recent intraday bar per symbol (micro fill price / valuation snapshot).

    Window function instead of ``DISTINCT ON`` — same SkipScan wrong-results hazard
    as ``get_latest_bars`` (see that docstring)."""
    rn = (
        func.row_number()
        .over(partition_by=IntradayBar.symbol, order_by=IntradayBar.ts.desc())
        .label("rn")
    )
    ranked = (
        select(IntradayBar, rn).where(IntradayBar.symbol.in_(symbols)).subquery()
    )
    latest = aliased(IntradayBar, ranked)
    stmt: Select[tuple[IntradayBar]] = select(latest).where(ranked.c.rn == 1)
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
    """Latest value per requested macro series (regime classifier input).

    Window function instead of ``DISTINCT ON`` — same SkipScan wrong-results hazard
    as ``get_latest_bars`` (see that docstring)."""
    rn = (
        func.row_number()
        .over(partition_by=MacroSeries.series_id, order_by=MacroSeries.ts.desc())
        .label("rn")
    )
    ranked = (
        select(MacroSeries, rn).where(MacroSeries.series_id.in_(series_ids)).subquery()
    )
    latest = aliased(MacroSeries, ranked)
    stmt: Select[tuple[MacroSeries]] = select(latest).where(ranked.c.rn == 1)
    return (await session.scalars(stmt)).all()
