"""Deferred market-on-open fills.

Until 2026-08-31 every daily order filled against the last STORED close. The job runs
at 08:00 UTC, before the US open, so that close belonged to the previous session: the
simulator traded at a price that had already happened when it decided, and one that
averaged 0.08% in its own favour on entries. Orders are now queued and filled at the
session's open — the first price the decision could actually get."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.contracts import OrderState
from backend.db.queries.portfolio_queries import (
    count_acted_orders_since,
    get_position,
)
from backend.tests import factories as f
from backend.trading.paper_broker import MARKET_ON_OPEN, PaperBroker

pytestmark = pytest.mark.integration
UTC = dt.timezone.utc
# place_order stamps the order with now(), so the session it fills at is "today":
# the bars below are seeded relative to the real clock, not to a fixed date.
NOW = dt.datetime.now(UTC)
TODAY = NOW.date()
YESTERDAY = TODAY - dt.timedelta(days=1)
LATER = NOW + dt.timedelta(days=1)
MUCH_LATER = NOW + dt.timedelta(days=15)


@pytest.fixture(autouse=True)
def _fixed_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIPPAGE_PCT", "0.001")
    monkeypatch.setenv("COMMISSION_PCT", "0")
    monkeypatch.setenv("COMMISSION_PER_ORDER", "0")


async def _seed_bar(session, symbol: str, day: dt.date, *, open_price: float, close: float) -> None:
    from backend.data_ingestion.ingest import upsert_bars

    ts = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
    await upsert_bars(session, [f.bar(symbol, ts=ts, close=close, open_price=open_price)])


async def test_queued_order_does_not_move_cash_or_positions(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    order = await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)

    assert order.status is OrderState.PENDING
    assert order.price is None
    assert await broker.get_cash() == Decimal("10000.00")
    assert await get_position(db_session, pid, "AAPL") is None


async def test_settlement_fills_at_the_open_not_the_prior_close(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    # Yesterday's close (what the old model would have paid) vs today's open: a 3% gap.
    await _seed_bar(db_session, "AAPL", YESTERDAY, open_price=100, close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)
    await _seed_bar(db_session, "AAPL", TODAY, open_price=103, close=105)

    filled = await broker.settle_open_orders(LATER)

    assert filled == 1
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("5.000000")
    # 103 * (1 + 0.001) — the open plus slippage, never the 100 close.
    assert await broker.get_cash() == Decimal("10000.00") - Decimal("5") * Decimal("103.103")


async def test_nothing_to_settle_until_the_open_exists(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await _seed_bar(db_session, "AAPL", YESTERDAY, open_price=100, close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)

    assert await broker.settle_open_orders(NOW) == 0
    assert await broker.get_cash() == Decimal("10000.00")


async def test_settlement_is_idempotent(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)
    await _seed_bar(db_session, "AAPL", TODAY, open_price=100, close=100)

    first = await broker.settle_open_orders(LATER)
    second = await broker.settle_open_orders(LATER)

    assert (first, second) == (1, 0)
    assert (await get_position(db_session, pid, "AAPL")).qty == Decimal("5.000000")


async def test_a_sell_the_stop_already_took_is_rejected_at_settlement(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100)
    await broker.place_order("AAPL", "sell", Decimal("5"), MARKET_ON_OPEN)
    # A protective stop sells the whole position before the open arrives.
    await f.seed_latest_bar(db_session, "AAPL", close=90)
    await broker.place_order("AAPL", "sell", Decimal("5"), "market")
    await _seed_bar(db_session, "AAPL", TODAY, open_price=95, close=95)

    assert await broker.settle_open_orders(LATER) == 0
    assert (await get_position(db_session, pid, "AAPL")).qty == Decimal("0.000000")


async def test_a_buy_that_no_longer_fits_the_cash_is_rejected(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=500)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)
    # Gaps up hard overnight: 5 shares no longer fit in 500 EUR.
    await _seed_bar(db_session, "AAPL", TODAY, open_price=200, close=200)

    assert await broker.settle_open_orders(LATER) == 0
    assert await broker.get_cash() == Decimal("500.00")
    assert await get_position(db_session, pid, "AAPL") is None


async def test_stale_pending_order_expires_instead_of_filling(db_session) -> None:
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)
    # No bar ever arrives; four sessions later the decision is meaningless.
    assert await broker.settle_open_orders(MUCH_LATER) == 0

    from sqlalchemy import select

    from backend.db.models import TradeOrder

    order = (
        await db_session.scalars(
            select(TradeOrder).where(TradeOrder.portfolio_id == pid)
        )
    ).one()
    assert order.status == OrderState.CANCELLED.value


async def test_a_pending_order_counts_as_having_traded_today(db_session) -> None:
    # The daily guard used to count fills only; with deferred fills that would let a
    # second run of the same day queue the whole batch again.
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("5"), MARKET_ON_OPEN)

    midnight = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    assert await count_acted_orders_since(db_session, pid, midnight) == 1
