from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import FundamentalsQuarterly


async def get_recent_fundamentals(
    session: AsyncSession, symbol: str, limit: int = 8
) -> Sequence[FundamentalsQuarterly]:
    """The most recent ``limit`` quarterly rows for a symbol, oldest → newest.

    Ordered ascending so the signal math can read the series left-to-right (YoY needs
    quarter t against t-4); the ``limit`` is applied to the newest rows."""
    stmt = (
        select(FundamentalsQuarterly)
        .where(FundamentalsQuarterly.symbol == symbol)
        .order_by(FundamentalsQuarterly.period_end.desc())
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return list(reversed(rows))
