from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
