from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import MacroSeries


async def get_latest_macro_values(
    session: AsyncSession, series_ids: Sequence[str], asof: dt.datetime
) -> dict[str, Decimal]:
    """Most recent value at/<= ``asof`` for each requested macro series.

    Window function instead of ``DISTINCT ON`` — TimescaleDB 2.27 SkipScan can return
    wrong rows for multi-key DISTINCT ON over a hypertable (see get_latest_bars).
    Series with no observation in range are simply absent from the returned map."""
    if not series_ids:
        return {}
    rn = (
        func.row_number()
        .over(partition_by=MacroSeries.series_id, order_by=MacroSeries.ts.desc())
        .label("rn")
    )
    ranked = (
        select(MacroSeries.series_id, MacroSeries.value, rn)
        .where(MacroSeries.series_id.in_(series_ids), MacroSeries.ts <= asof)
        .subquery()
    )
    stmt = select(ranked.c.series_id, ranked.c.value).where(ranked.c.rn == 1)
    rows = (await session.execute(stmt)).all()
    return {series_id: value for series_id, value in rows}
