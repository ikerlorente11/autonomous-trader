"""Idempotent upsert + read queries against the real test DB (rollback-isolated)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from backend.data_ingestion.ingest import upsert_bars
from backend.db.models import MarketBar
from backend.db.queries.market_queries import (
    count_bars_per_symbol,
    get_latest_bars,
)
from backend.db.queries.portfolio_queries import (
    deactivate_watchlist_symbol,
    get_active_watchlist,
)
from backend.tests import factories as f

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc


async def _count(session, symbol: str) -> int:
    return int(
        await session.scalar(
            sa.select(sa.func.count()).select_from(MarketBar).where(MarketBar.symbol == symbol)
        )
    )


async def test_upsert_is_idempotent(db_session) -> None:
    bars = f.bar_series("AAPL", closes=[10, 11, 12], start=dt.date(2026, 5, 1))
    await upsert_bars(db_session, bars)
    await upsert_bars(db_session, bars)  # same day-range again
    assert await _count(db_session, "AAPL") == 3  # no duplicates


async def test_upsert_updates_on_conflict(db_session) -> None:
    ts = dt.datetime(2026, 5, 1, tzinfo=UTC)
    await f.seed_latest_bar(db_session, "AAPL", close=10, ts=ts)
    await f.seed_latest_bar(db_session, "AAPL", close=99, ts=ts)  # same PK (symbol, ts)
    assert await _count(db_session, "AAPL") == 1
    row = await db_session.get(MarketBar, ("AAPL", ts))
    assert row.close == Decimal("99.000000")


async def test_count_bars_and_latest_bar(db_session) -> None:
    await f.seed_bars(db_session, "AAPL", closes=[10, 11, 12], start=dt.date(2026, 5, 1))
    await f.seed_bars(db_session, "MSFT", closes=[20, 21], start=dt.date(2026, 5, 1))
    counts = await count_bars_per_symbol(
        db_session, ["AAPL", "MSFT"], dt.datetime(2026, 4, 1, tzinfo=UTC), dt.datetime(2026, 6, 1, tzinfo=UTC)
    )
    assert counts["AAPL"] == 3 and counts["MSFT"] == 2
    latest = {b.symbol: b.close for b in await get_latest_bars(db_session, ["AAPL", "MSFT"])}
    assert latest["AAPL"] == Decimal("12.000000")
    assert latest["MSFT"] == Decimal("21.000000")


async def test_active_watchlist_excludes_deactivated(db_session) -> None:
    await f.seed_watchlist(db_session, "AAPL", "MSFT", "TSLA")
    await deactivate_watchlist_symbol(db_session, "MSFT")
    active = [w.symbol for w in await get_active_watchlist(db_session)]
    assert active == ["AAPL", "TSLA"]  # sorted, MSFT dropped
