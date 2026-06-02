from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.api.schemas import _SYMBOL_RE, QuoteEntry, WatchlistCreate, WatchlistEntry
from backend.contracts import OHLCVBar
from backend.data_ingestion.providers.yfinance_provider import YFinanceProvider
from backend.db.queries.market_queries import get_bars_range, get_latest_bars
from backend.db.queries.portfolio_queries import (
    deactivate_watchlist_symbol,
    get_active_watchlist,
    get_latest_analysis_ts,
    get_top_ranked_signals,
    upsert_watchlist_symbol,
)

router = APIRouter(prefix="/api/market", tags=["market"])

# Each requested symbol becomes a sequential outbound HTTP call; cap the batch so a
# single request cannot fan out into a long-running outbound storm (H5).
_MAX_QUOTE_SYMBOLS = 50


def _validate_symbol(symbol: str) -> str:
    """Normalize and validate a symbol before it reaches an outbound URL path or query.
    Rejects anything outside the watchlist charset to block path injection / SSRF (H4)."""
    normalized = symbol.strip().upper()
    if not _SYMBOL_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail=f"invalid symbol: {symbol!r}")
    return normalized


@router.get("/quotes", response_model=list[QuoteEntry])
async def market_quotes(symbols: str = Query(...)) -> list[QuoteEntry]:
    requested = list(dict.fromkeys(_validate_symbol(s) for s in symbols.split(",") if s.strip()))
    if not requested:
        return []
    if len(requested) > _MAX_QUOTE_SYMBOLS:
        raise HTTPException(
            status_code=422,
            detail=f"too many symbols (max {_MAX_QUOTE_SYMBOLS})",
        )
    prices = await YFinanceProvider().fetch_live_prices(requested)
    return [QuoteEntry(symbol=s, price=prices[s]) for s in requested if s in prices]


@router.get("/bars/{symbol}", response_model=list[OHLCVBar])
async def market_bars(
    symbol: str = Path(...),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[OHLCVBar]:
    symbol = _validate_symbol(symbol)
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


@router.post("/watchlist", response_model=WatchlistEntry, status_code=201)
async def add_watchlist_symbol(
    payload: WatchlistCreate,
    session: AsyncSession = Depends(get_session),
) -> WatchlistEntry:
    entry = await upsert_watchlist_symbol(
        session,
        payload.symbol,
        sector=payload.sector,
        asset_class=payload.asset_class,
    )
    await session.commit()
    return WatchlistEntry(
        symbol=entry.symbol, sector=entry.sector, asset_class=entry.asset_class
    )


@router.delete("/watchlist/{symbol}", response_model=WatchlistEntry)
async def remove_watchlist_symbol(
    symbol: str = Path(...),
    session: AsyncSession = Depends(get_session),
) -> WatchlistEntry:
    normalized = symbol.strip().upper()
    removed = await deactivate_watchlist_symbol(session, normalized)
    await session.commit()
    if not removed:
        raise HTTPException(status_code=404, detail=f"{normalized} not on watchlist")
    return WatchlistEntry(symbol=normalized)
