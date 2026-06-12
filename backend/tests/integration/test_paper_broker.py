"""PaperBroker against the real test DB — fills, ledger cash, rejections."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.contracts import OrderState
from backend.db.queries.portfolio_queries import get_position
from backend.tests import factories as f
from backend.trading.paper_broker import PaperBroker

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fixed_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIPPAGE_PCT", "0.001")


async def _broker(db_session, *, deposit: float = 10_000.0) -> tuple[PaperBroker, int]:
    pid = await f.seed_portfolio(db_session, deposit=deposit)
    return PaperBroker(db_session, pid), pid


async def test_buy_fills_creates_position_and_spends_cash(db_session) -> None:
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    order = await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    assert order.status is OrderState.FILLED
    assert order.price == Decimal("100.100000")  # 100 * (1 + 0.001)

    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("5.000000")
    # cash 10000 - 100.1*5 = 9499.5 ; equity 5*100 = 500 ; total 9999.5 (slippage cost)
    assert await broker.get_account_balance() == Decimal("9999.5")


async def test_sell_more_than_held_is_rejected(db_session) -> None:
    broker, _ = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    order = await broker.place_order("AAPL", "sell", Decimal("3"), "market")
    assert order.status is OrderState.REJECTED
    assert "insufficient" in (order.reason or "")


async def test_no_market_price_rejected(db_session) -> None:
    broker, _ = await _broker(db_session)  # no bar seeded for ZZZ
    order = await broker.place_order("ZZZ", "buy", Decimal("1"), "market")
    assert order.status is OrderState.REJECTED
    assert "no market price" in (order.reason or "")


async def test_buy_then_partial_sell_reduces_position(db_session) -> None:
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    sell = await broker.place_order("AAPL", "sell", Decimal("2"), "market")
    assert sell.status is OrderState.FILLED
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("3.000000")


async def test_commission_is_charged_and_drags_cash(
    db_session, monkeypatch
) -> None:
    # P10: a commission (pct of notional + flat per-order) is deducted from cash and
    # stored on the order, so churn has a visible cost in the A/B. Default is 0.
    monkeypatch.setenv("COMMISSION_PCT", "0.002")
    monkeypatch.setenv("COMMISSION_PER_ORDER", "0.5")
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    order = await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    assert order.status is OrderState.FILLED
    # fill 100.1 (0.1% slippage); notional 500.5; commission 500.5*0.002 + 0.5 = 1.501
    assert order.commission == Decimal("1.501")
    # cash 10000 - 500.5 (notional) - 1.501 (commission) = 9497.999
    assert await broker.get_cash() == Decimal("9497.999")


async def test_no_commission_by_default(db_session) -> None:
    # With the env unset, commission is 0 — existing behaviour is byte-for-byte unchanged.
    broker, _ = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    order = await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    assert order.commission == Decimal("0")
    assert await broker.get_cash() == Decimal("9499.5")  # 10000 - 100.1*5


async def test_buy_with_insufficient_cash_rejected(db_session) -> None:
    # A real broker rejects an unfunded buy; the paper double must too, or the
    # slippage/commission overshoot drives the reconstructed cash ledger negative.
    broker, _ = await _broker(db_session, deposit=100.0)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    order = await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    assert order.status is OrderState.REJECTED
    assert "insufficient cash" in (order.reason or "")
    assert await broker.get_cash() == Decimal("100")


async def test_full_sell_clears_high_water_mark(db_session) -> None:
    # The trailing-stop peak belongs to the trip that set it: a closed row keeping
    # it would seed the NEXT entry's stop above the price that just stopped out,
    # firing the stop on the first tick after re-entry (buy -> sell churn loop).
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    pos = await get_position(db_session, pid, "AAPL")
    pos.high_water_mark = Decimal("130")  # simulate the protective_sell ratchet
    await db_session.flush()

    await broker.place_order("AAPL", "sell", Decimal("5"), "market")
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.high_water_mark is None


async def test_reentry_buy_starts_fresh_position(db_session) -> None:
    # Buying into a flat row is a new trip: stale peak dropped, avg_cost = the new
    # fill (not blended with the closed trip's basis).
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    await broker.place_order("AAPL", "sell", Decimal("5"), "market")
    pos = await get_position(db_session, pid, "AAPL")
    pos.high_water_mark = Decimal("130")  # pre-fix data: stale peak on a flat row
    await db_session.flush()

    buy = await broker.place_order("AAPL", "buy", Decimal("2"), "market")
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("2.000000")
    assert pos.avg_cost == buy.price
    assert pos.high_water_mark is None


async def test_full_sell_clears_unrealized_pnl(db_session) -> None:
    # A closed (qty=0) row must not retain a stale unrealized P&L (diagnostics P8):
    # the app filters qty != 0, but raw/analytics sums over portfolio_positions would
    # otherwise count a phantom mark on a position that no longer exists.
    broker, pid = await _broker(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    await broker.place_order("AAPL", "buy", Decimal("5"), "market")
    pos = await get_position(db_session, pid, "AAPL")
    pos.unrealized_pnl = Decimal("123.45")  # simulate a prior mark from update_positions
    await db_session.flush()

    sell = await broker.place_order("AAPL", "sell", Decimal("5"), "market")
    assert sell.status is OrderState.FILLED
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("0.000000")
    assert pos.unrealized_pnl == Decimal("0")
