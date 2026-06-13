"""Microtrading universe selection — pick the day-tradeable sub-universe.

Day trading lives or dies on liquidity: tight spreads and depth are only found in the
most-traded names, and at micro ticket sizes an illiquid symbol's spread alone erases
the edge (research §costs). So each session the watchlist is ranked by average daily
dollar-volume (close×volume) and the top N liquid names are polled/traded — the rest
are skipped. Selection is runtime data over the existing watchlist; nothing hardcoded.

Why dollar-volume for *selection* and not RVOL: RVOL (today vs average) is an entry-time
signal computed from intraday bars at scoring time, not a pre-session liquidity filter.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.queries.market_queries import avg_dollar_volume

_DEFAULT_LOOKBACK_DAYS = 20
_DEFAULT_MIN_DOLLAR_VOLUME = 0.0


def micro_universe_lookback_days() -> int:
    try:
        return max(1, int(os.environ.get("MICRO_UNIVERSE_LOOKBACK_DAYS", "")))
    except ValueError:
        return _DEFAULT_LOOKBACK_DAYS


def micro_min_dollar_volume() -> float:
    """Liquidity floor (avg daily $-volume) a symbol must clear to be day-traded.
    Default 0 = no floor (rank-only); raise it to exclude thin names."""
    try:
        return max(0.0, float(os.environ.get("MICRO_MIN_DOLLAR_VOLUME", "")))
    except ValueError:
        return _DEFAULT_MIN_DOLLAR_VOLUME


async def select_micro_universe(
    session: AsyncSession,
    symbols: Sequence[str],
    asof: dt.datetime,
    *,
    limit: int,
    lookback_days: int | None = None,
    min_dollar_volume: float | None = None,
) -> list[str]:
    """Top-``limit`` most-liquid symbols from ``symbols`` by avg dollar-volume.

    Returns at most ``limit`` symbols, most-liquid first. Symbols without enough bar
    history (absent from the dollar-volume map) or below the floor are excluded. Empty
    input or no history → empty list, and the caller decides how to degrade."""
    if not symbols or limit <= 0:
        return []
    lookback = lookback_days if lookback_days is not None else micro_universe_lookback_days()
    floor = min_dollar_volume if min_dollar_volume is not None else micro_min_dollar_volume()
    start = asof - dt.timedelta(days=lookback)
    dollar_volume = await avg_dollar_volume(session, list(symbols), start, asof)
    ranked = sorted(
        (s for s in symbols if dollar_volume.get(s, 0.0) >= floor and s in dollar_volume),
        key=lambda s: dollar_volume[s],
        reverse=True,
    )
    return ranked[:limit]
