"""m3 anti-churn guards in PortfolioManager: daily entry budget + minimum hold."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.analysis.config import load_strategy_config
from backend.contracts import OrderSide, SignalAction
from backend.db.queries.portfolio_queries import get_position
from backend.tests import factories as f
from backend.tests.factories import symbol_score
from backend.contracts import RankedSymbol
from backend.trading.paper_broker import PaperBroker
from backend.trading.portfolio_manager import PortfolioManager

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _no_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIPPAGE_PCT", "0")


def _sell(symbol: str, rank: int = 1) -> RankedSymbol:
    return RankedSymbol(rank=rank, score=symbol_score(symbol, 20, action=SignalAction.SELL))


async def _m3_manager(db_session, *, deposit: float = 10_000.0):
    pid = await f.seed_portfolio(db_session, deposit=deposit, kind="micro")
    manager = PortfolioManager(
        PaperBroker(db_session, pid),
        db_session,
        pid,
        config=load_strategy_config(label="m3"),
    )
    return manager, pid


async def test_max_trades_per_day_caps_entries(db_session) -> None:
    pm, pid = await _m3_manager(db_session)
    symbols = [f"SY{i}" for i in range(8)]
    for s in symbols:
        await f.seed_latest_bar(db_session, s, close=100)

    orders = await pm.execute_signals(
        [f.ranked(s, 80, rank=i + 1) for i, s in enumerate(symbols)]
    )

    buys = [o for o in orders if o.side is OrderSide.BUY]
    assert len(buys) == 5  # m3 budget
    # Budget follows rank: the top-5 ranked names got the fills.
    assert {o.symbol for o in buys} == set(symbols[:5])

    # A later run the same day has no budget left.
    more = await pm.execute_signals([f.ranked("SY7", 90, rank=1)])
    assert [o for o in more if o.side is OrderSide.BUY] == []


async def test_min_hold_blocks_young_signal_exit_not_old(db_session) -> None:
    pm, pid = await _m3_manager(db_session)
    await f.seed_latest_bar(db_session, "AAA", close=100)

    # Fresh buy -> a signal exit seconds later must be ignored (younger than 60 min).
    await pm.execute_signals([f.ranked("AAA", 80, rank=1)])
    orders = await pm.execute_signals([_sell("AAA")])
    assert orders == []
    pos = await get_position(db_session, pid, "AAA")
    assert pos.qty > 0

    # Age the buy fill beyond the hold window -> the exit goes through.
    from sqlalchemy import text

    await db_session.execute(
        text(
            "UPDATE trade_orders SET ts = ts - interval '2 hours' "
            "WHERE portfolio_id = :pid AND side = 'buy'"
        ),
        {"pid": pid},
    )
    orders = await pm.execute_signals([_sell("AAA")])
    assert len(orders) == 1 and orders[0].side is OrderSide.SELL
    pos = await get_position(db_session, pid, "AAA")
    assert pos.qty == Decimal("0.000000")


async def test_daily_config_without_knobs_is_unchanged(db_session) -> None:
    # The base (daily) config sets neither knob: entries uncapped by the budget,
    # exits never blocked by age.
    pid = await f.seed_portfolio(db_session, deposit=10_000)
    pm = PortfolioManager(
        PaperBroker(db_session, pid), db_session, pid, config=load_strategy_config()
    )
    await f.seed_latest_bar(db_session, "AAA", close=100)
    await pm.execute_signals([f.ranked("AAA", 80, rank=1)])
    orders = await pm.execute_signals([_sell("AAA")])  # immediate exit allowed
    assert len(orders) == 1 and orders[0].side is OrderSide.SELL
