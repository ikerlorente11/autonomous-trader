from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import MacroSeries


async def get_latest_macro_values(
    session: AsyncSession, series_ids: Sequence[str], asof: dt.datetime
) -> dict[str, Decimal]:
    """Most recent value at/<= ``asof`` for each requested macro series.

    ``DISTINCT ON (series_id)`` keeps the newest row per series; series with no
    observation in range are simply absent from the returned map."""
    if not series_ids:
        return {}
    stmt = (
        select(MacroSeries.series_id, MacroSeries.value)
        .where(MacroSeries.series_id.in_(series_ids), MacroSeries.ts <= asof)
        .distinct(MacroSeries.series_id)
        .order_by(MacroSeries.series_id, MacroSeries.ts.desc())
    )
    rows = (await session.execute(stmt)).all()
    return {series_id: value for series_id, value in rows}
