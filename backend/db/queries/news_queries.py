from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import NewsSentiment


async def get_recent_news_counts(
    session: AsyncSession, symbol: str, limit: int = 30
) -> list[int]:
    """The most recent ``limit`` daily article counts for a symbol, oldest → newest."""
    stmt = (
        select(NewsSentiment.article_count)
        .where(NewsSentiment.symbol == symbol)
        .order_by(NewsSentiment.ts.desc())
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return [int(c) for c in reversed(rows)]
