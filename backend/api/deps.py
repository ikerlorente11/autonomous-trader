from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.queries.portfolio_queries import (
    get_portfolio,
    resolve_default_portfolio_id,
)
from backend.db.session import async_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session


async def resolve_portfolio(
    portfolio_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> int:
    """Active-portfolio resolver: the ``?portfolio_id=`` query param if given (and
    valid), otherwise the default (first active). 404 on unknown, 409 if none exist."""
    if portfolio_id is not None:
        if await get_portfolio(session, portfolio_id) is None:
            raise HTTPException(
                status_code=404, detail=f"portfolio {portfolio_id} not found"
            )
        return portfolio_id
    default_id = await resolve_default_portfolio_id(session)
    if default_id is None:
        raise HTTPException(status_code=409, detail="no portfolios exist")
    return default_id
