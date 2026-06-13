"""Intraday upsert idempotency + portfolio-kind gating against the test DB (rollback)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from backend.contracts import IntradayBar
from backend.data_ingestion.intraday_ingest import upsert_intraday_bars
from backend.db.models import IntradayBar as IntradayBarRow
from backend.db.queries.portfolio_queries import create_portfolio, list_portfolios

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc


def _bar(symbol: str, ts: dt.datetime, close: float) -> IntradayBar:
    price = Decimal(str(close))
    return IntradayBar(
        symbol=symbol, ts=ts, open=price, high=price, low=price, close=price, volume=1000
    )


async def _count(session, symbol: str) -> int:
    return int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(IntradayBarRow)
            .where(IntradayBarRow.symbol == symbol)
        )
    )


async def test_intraday_upsert_is_idempotent(db_session) -> None:
    t0 = dt.datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    bars = [_bar("AAPL", t0 + dt.timedelta(minutes=5 * i), 10 + i) for i in range(3)]
    await upsert_intraday_bars(db_session, bars)
    await upsert_intraday_bars(db_session, bars)  # same bars again
    assert await _count(db_session, "AAPL") == 3  # no duplicates


async def test_intraday_upsert_updates_on_conflict(db_session) -> None:
    ts = dt.datetime(2026, 6, 12, 13, 30, tzinfo=UTC)
    await upsert_intraday_bars(db_session, [_bar("AAPL", ts, 10)])
    await upsert_intraday_bars(db_session, [_bar("AAPL", ts, 99)])  # same PK
    assert await _count(db_session, "AAPL") == 1
    row = await db_session.get(IntradayBarRow, ("AAPL", ts))
    assert row.close == Decimal("99.000000")


async def test_list_portfolios_filters_by_kind(db_session) -> None:
    await create_portfolio(db_session, "swing", Decimal("500"), kind="daily")
    await create_portfolio(db_session, "micro", Decimal("500"), kind="micro")
    await db_session.flush()

    daily = await list_portfolios(db_session, kinds=("daily",))
    micro = await list_portfolios(db_session, kinds=("micro",))
    everything = await list_portfolios(db_session)

    assert [p.name for p in daily] == ["swing"]
    assert [p.name for p in micro] == ["micro"]
    assert {p.name for p in everything} == {"swing", "micro"}


async def test_create_portfolio_defaults_to_daily_kind(db_session) -> None:
    portfolio = await create_portfolio(db_session, "legacy", Decimal("100"))
    await db_session.flush()
    assert portfolio.kind == "daily"
