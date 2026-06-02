from __future__ import annotations

import datetime as dt
import math

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.performance.metrics import build_round_trips
from backend.api.deps import get_session, resolve_portfolio
from backend.contracts import OrderSide, OrderState, TradeRecord, TradeRoundTrip
from backend.db.queries.portfolio_queries import get_filled_orders, get_filtered_orders

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeRecord])
async def trades(
    symbol: str | None = Query(default=None),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> list[TradeRecord]:
    rows = await get_filtered_orders(
        session, portfolio_id, symbol=symbol, start=start, end=end, limit=limit
    )
    return [
        TradeRecord(
            id=r.id,
            symbol=r.symbol,
            side=OrderSide(r.side),
            qty=r.qty,
            price=r.price,
            status=OrderState(r.status),
            reason=r.reason,
            strategy_version=r.strategy_version,
            ts=r.ts,
        )
        for r in rows
    ]


@router.get("/round-trips", response_model=list[TradeRoundTrip])
async def round_trips(
    portfolio_id: int = Depends(resolve_portfolio),
    session: AsyncSession = Depends(get_session),
) -> list[TradeRoundTrip]:
    """Closed FIFO round trips with realized P&L — the entry/exit pairing the headline
    win-rate / profit-factor metrics are built on, surfaced for the trades view."""
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
    out: list[TradeRoundTrip] = []
    for t in trips.itertuples(index=False):
        rp = float(t.return_pct)
        out.append(
            TradeRoundTrip(
                symbol=t.symbol,
                entry_ts=t.entry_ts,
                exit_ts=t.exit_ts,
                qty=float(t.qty),
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price),
                pnl=float(t.pnl),
                return_pct=rp if math.isfinite(rp) else None,
                holding_days=int(t.holding_days),
            )
        )
    return out
