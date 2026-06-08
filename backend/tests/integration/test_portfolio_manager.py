"""PortfolioManager against the real test DB, driven through the PaperBroker seam.

Slippage is pinned to 0 so fills land at the bar close and the sizing/NAV maths are
exact. The manager only ever touches the BrokerAdapter Protocol (PaperBroker here),
never a concrete broker — the sacred seam stays intact."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.analysis.config import load_strategy_config
from backend.contracts import OrderSide, OrderState, RankedSymbol, SignalAction
from backend.db.queries.portfolio_queries import (
    compute_cash,
    get_nav_history,
    get_open_positions,
    get_position,
)
from backend.tests import factories as f
from backend.tests.factories import symbol_score
from backend.trading.paper_broker import PaperBroker
from backend.trading.portfolio_manager import PortfolioManager

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _no_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIPPAGE_PCT", "0")


async def _manager(db_session, *, deposit: float = 10_000.0) -> tuple[PortfolioManager, int]:
    pid = await f.seed_portfolio(db_session, deposit=deposit)
    return PortfolioManager(PaperBroker(db_session, pid), db_session, pid), pid


def _sell(symbol: str) -> RankedSymbol:
    return RankedSymbol(rank=1, score=symbol_score(symbol, 20, action=SignalAction.SELL))


# --------------------------------------------------------------------------- #
# execute_signals
# --------------------------------------------------------------------------- #
async def test_buy_signal_opens_sized_position(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    orders = await pm.execute_signals([f.ranked("AAPL", 80, rank=1)])

    assert len(orders) == 1
    assert orders[0].status is OrderState.FILLED
    assert orders[0].side is OrderSide.BUY
    # 5% of 10 000 / 100 = 5 shares.
    pos = await get_position(db_session, pid, "AAPL")
    assert pos.qty == Decimal("5.000000")
    assert await compute_cash(db_session, pid) == Decimal("9500")  # 10 000 − 5·100


async def test_v2_no_pyramiding_skips_held_name(db_session) -> None:
    # P6: v2 disallows pyramiding -> a BUY for an already-held name is dropped.
    pid = await f.seed_portfolio(db_session, deposit=10_000.0)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100.0)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    pm = PortfolioManager(
        PaperBroker(db_session, pid), db_session, pid,
        config=load_strategy_config(label="v2"),
    )
    orders = await pm.execute_signals([f.ranked("AAPL", 80, rank=1)])
    assert orders == []


async def test_v2_cooldown_blocks_recent_rebuy(db_session) -> None:
    # P2: v2 blocks re-buying a name sold within the cooldown window.
    pid = await f.seed_portfolio(db_session, deposit=10_000.0)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("3"), "market")
    await broker.place_order("AAPL", "sell", Decimal("3"), "market")  # recent filled sell
    pm = PortfolioManager(
        broker, db_session, pid, config=load_strategy_config(label="v2")
    )
    orders = await pm.execute_signals([f.ranked("AAPL", 80, rank=1)])
    assert orders == []


async def test_base_config_allows_rebuy(db_session) -> None:
    # Control: with no version config (v1/base), the rebuy is allowed (unchanged behavior).
    pid = await f.seed_portfolio(db_session, deposit=10_000.0)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", Decimal("3"), "market")
    await broker.place_order("AAPL", "sell", Decimal("3"), "market")
    pm = PortfolioManager(broker, db_session, pid)  # no config -> defaults
    orders = await pm.execute_signals([f.ranked("AAPL", 80, rank=1)])
    assert len(orders) == 1


async def test_sell_signal_exits_held_position(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100.0)
    await f.seed_latest_bar(db_session, "AAPL", close=110)

    orders = await pm.execute_signals([_sell("AAPL")])

    assert len(orders) == 1
    assert orders[0].status is OrderState.FILLED
    assert orders[0].side is OrderSide.SELL
    pos = await get_position(db_session, pid, "AAPL")
    assert pos is None or pos.qty == Decimal("0")


async def test_sell_signal_for_unheld_symbol_is_skipped(db_session) -> None:
    pm, _ = await _manager(db_session)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    orders = await pm.execute_signals([_sell("AAPL")])  # nothing held

    assert orders == []


async def test_exits_run_before_entries(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_position(db_session, pid, "MSFT", qty=4, avg_cost=50.0)
    await f.seed_latest_bar(db_session, "MSFT", close=50)
    await f.seed_latest_bar(db_session, "AAPL", close=100)

    orders = await pm.execute_signals([_sell("MSFT"), f.ranked("AAPL", 90, rank=1)])

    assert [o.side for o in orders] == [OrderSide.SELL, OrderSide.BUY]
    assert orders[0].symbol == "MSFT" and orders[1].symbol == "AAPL"


# --------------------------------------------------------------------------- #
# update_positions
# --------------------------------------------------------------------------- #
async def test_update_positions_marks_and_flags_stale(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100.0)
    await f.seed_position(db_session, pid, "MSFT", qty=2, avg_cost=50.0)  # no bar -> stale
    await f.seed_latest_bar(db_session, "AAPL", close=110)

    updated, stale = await pm.update_positions()

    assert updated == 1
    assert stale == ["MSFT"]
    aapl = await get_position(db_session, pid, "AAPL")
    assert aapl.current_price == Decimal("110.000000")
    assert aapl.unrealized_pnl == Decimal("50.000000")  # (110-100)*5


# --------------------------------------------------------------------------- #
# snapshot_nav
# --------------------------------------------------------------------------- #
async def test_snapshot_nav_persists_cash_equity_total(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100.0)
    await f.seed_latest_bar(db_session, "AAPL", close=110)

    nav = await pm.snapshot_nav(ts=dt.datetime(2026, 6, 1, tzinfo=UTC))

    assert nav.cash == Decimal("10000")  # deposit only, no filled orders
    assert nav.equity == Decimal("550")  # 5 * 110
    assert nav.total == Decimal("10550")
    assert nav.benchmark_value is None  # no SPY bar seeded


async def test_snapshot_nav_is_idempotent_per_timestamp(db_session) -> None:
    pm, pid = await _manager(db_session)
    await f.seed_position(db_session, pid, "AAPL", qty=5, avg_cost=100.0)
    await f.seed_latest_bar(db_session, "AAPL", close=110)
    ts = dt.datetime(2026, 6, 1, tzinfo=UTC)

    await pm.snapshot_nav(ts=ts)
    await pm.snapshot_nav(ts=ts)

    rows = await get_nav_history(
        db_session, pid, dt.datetime(2020, 1, 1, tzinfo=UTC), dt.datetime(2030, 1, 1, tzinfo=UTC)
    )
    assert len(rows) == 1
    assert rows[0].total == Decimal("10550")


async def test_no_open_positions_update_returns_zero(db_session) -> None:
    pm, pid = await _manager(db_session)
    assert await pm.update_positions() == (0, [])
    assert await get_open_positions(db_session, pid) == []
