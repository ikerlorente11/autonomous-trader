from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.contracts import OrderSide, OrderState, TradeRecord
from backend.db.queries.portfolio_queries import get_filtered_orders

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeRecord])
async def trades(
    symbol: str | None = Query(default=None),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[TradeRecord]:
    rows = await get_filtered_orders(
        session, symbol=symbol, start=start, end=end, limit=limit
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
