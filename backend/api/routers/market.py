from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.api.schemas import WatchlistEntry
from backend.contracts import OHLCVBar
from backend.db.queries.market_queries import get_bars_range, get_latest_bars
from backend.db.queries.portfolio_queries import (
    get_active_watchlist,
    get_latest_analysis_ts,
    get_top_ranked_signals,
)

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/bars/{symbol}", response_model=list[OHLCVBar])
async def market_bars(
    symbol: str = Path(...),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[OHLCVBar]:
    end = end or dt.datetime.now(dt.timezone.utc)
    start = start or (end - dt.timedelta(days=180))
    rows = await get_bars_range(session, symbol, start, end)
    return [
        OHLCVBar(
            symbol=r.symbol,
            ts=r.ts,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
            adj_close=r.adj_close,
        )
        for r in rows
    ]


@router.get("/watchlist", response_model=list[WatchlistEntry])
async def market_watchlist(
    session: AsyncSession = Depends(get_session),
) -> list[WatchlistEntry]:
    entries = await get_active_watchlist(session)
    if not entries:
        return []
    symbols = [w.symbol for w in entries]
    prices: dict[str, Decimal] = {}
    for bar in await get_latest_bars(session, symbols):
        prices[bar.symbol] = bar.close
    scores: dict[str, tuple[Decimal, str]] = {}
    asof = await get_latest_analysis_ts(session)
    if asof is not None:
        for sig in await get_top_ranked_signals(session, asof, limit=len(symbols)):
            scores[sig.symbol] = (sig.score, sig.action)
    out: list[WatchlistEntry] = []
    for w in entries:
        score_action = scores.get(w.symbol)
        out.append(
            WatchlistEntry(
                symbol=w.symbol,
                sector=w.sector,
                asset_class=w.asset_class,
                latest_price=prices.get(w.symbol),
                score=score_action[0] if score_action else None,
                action=score_action[1] if score_action else None,
                ts=asof,
            )
        )
    return out
