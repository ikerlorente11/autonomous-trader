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
