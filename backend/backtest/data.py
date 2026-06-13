"""Load everything the backtester needs from the DB in one pass (read-only)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select

from backend.analysis.signals.macro.regime import regime_series_ids
from backend.db.models import FundamentalsQuarterly, MacroSeries
from backend.db.queries.market_queries import get_bars_range
from backend.db.queries.portfolio_queries import get_active_watchlist
from backend.db.session import async_session

# Mirror the live job: 400 calendar days of bars feed each scoring day, so the
# replay needs that much warmup before its first day.
_WARMUP_DAYS = 420


def _bars_to_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [float(r.open) for r in rows],
            "high": [float(r.high) for r in rows],
            "low": [float(r.low) for r in rows],
            "close": [float(r.close) for r in rows],
            "volume": [int(r.volume) for r in rows],
        },
        index=[r.ts for r in rows],
    )


async def load_backtest_data(
    start: dt.date, end: dt.date
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series], dict[str, list[tuple[dt.date, dict]]]]:
    """(bars frames, macro series by id, fundamentals quarters by symbol)."""
    start_dt = dt.datetime.combine(
        start - dt.timedelta(days=_WARMUP_DAYS), dt.time(), tzinfo=dt.timezone.utc
    )
    end_dt = dt.datetime.combine(end, dt.time(23, 59), tzinfo=dt.timezone.utc)
    async with async_session() as session:
        watchlist = await get_active_watchlist(session)
        frames: dict[str, pd.DataFrame] = {}
        for entry in watchlist:
            rows = await get_bars_range(session, entry.symbol, start_dt, end_dt)
            if rows:
                frames[entry.symbol] = _bars_to_frame(rows)

        macro: dict[str, pd.Series] = {}
        for series_id in regime_series_ids():
            result = await session.scalars(
                select(MacroSeries)
                .where(MacroSeries.series_id == series_id, MacroSeries.ts <= end_dt)
                .order_by(MacroSeries.ts)
            )
            rows = result.all()
            if rows:
                macro[series_id] = pd.Series(
                    [float(r.value) for r in rows], index=[r.ts.date() for r in rows]
                )

        fundamentals: dict[str, list[tuple[dt.date, dict]]] = {}
        result = await session.scalars(
            select(FundamentalsQuarterly).order_by(
                FundamentalsQuarterly.symbol, FundamentalsQuarterly.period_end
            )
        )
        for row in result.all():
            fundamentals.setdefault(row.symbol, []).append((row.period_end, row.line_items))

    return frames, macro, fundamentals
