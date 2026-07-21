"""run_micro + micro_eod_flatten jobs end-to-end against the real test DB."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from backend.db.models import PortfolioPosition, TradeOrder
from backend.db.session import async_session
from backend.scheduler import jobs
from backend.tests import factories as f

pytestmark = pytest.mark.integration
UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _market_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "is_market_open_now", lambda: True)
    # Mid-session by default: run_micro must trade, flatten must no-op. Flatten
    # tests patch is_near_market_close back to True locally.
    monkeypatch.setattr(jobs, "is_near_market_close", lambda *_a, **_k: False)
    monkeypatch.setenv("SLIPPAGE_PCT", "0.001")


async def _orders(pid: int, side: str) -> list[TradeOrder]:
    async with async_session() as s:
        rows = (
            await s.scalars(
                sa.select(TradeOrder).where(
                    TradeOrder.portfolio_id == pid, TradeOrder.side == side
                )
            )
        ).all()
    return list(rows)


async def _position(pid: int, symbol: str) -> PortfolioPosition | None:
    async with async_session() as s:
        return await s.get(PortfolioPosition, (pid, symbol))


async def test_run_micro_enters_on_intraday_signal(clean_db) -> None:
    now = dt.datetime.now(UTC)
    async with async_session() as s:
        pid = await f.seed_portfolio(s, name="micro-test", deposit=10_000, kind="micro")
        await f.seed_watchlist(s, "AAA")
        # Daily bars → liquidity ranking picks AAA into the micro universe.
        await f.seed_bars(s, "AAA", closes=[50, 50, 50], start=(now - dt.timedelta(days=3)).date())
        # Ascending intraday series → high RSI/trend → BUY under the base config.
        closes = [float(50 + i) for i in range(40)]
        await f.seed_intraday_bars(
            s, "AAA", closes=closes, start=now - dt.timedelta(hours=4)
        )
        await s.commit()

    await jobs.run_micro()

    buys = await _orders(pid, "buy")
    assert buys, "run_micro should open a position on the ascending intraday signal"
    assert buys[0].status == "filled"
    # filled off the LAST intraday close (89), not the daily close (50).
    assert buys[0].price > Decimal("80")


async def test_run_micro_skips_daily_portfolios(clean_db) -> None:
    now = dt.datetime.now(UTC)
    async with async_session() as s:
        daily_pid = await f.seed_portfolio(s, name="daily-test", deposit=10_000, kind="daily")
        await f.seed_watchlist(s, "AAA")
        await f.seed_bars(s, "AAA", closes=[50, 50, 50], start=(now - dt.timedelta(days=3)).date())
        await f.seed_intraday_bars(
            s, "AAA", closes=[float(50 + i) for i in range(40)], start=now - dt.timedelta(hours=4)
        )
        await s.commit()

    await jobs.run_micro()
    assert await _orders(daily_pid, "buy") == []  # daily portfolios are never micro-traded


async def test_run_micro_skips_inside_flatten_window(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In the flatten window run_micro must stand down: a buy here is instant churn
    # and a signal exit here races the flatten sell (the phantom-sell bug).
    monkeypatch.setattr(jobs, "is_near_market_close", lambda *_a, **_k: True)
    now = dt.datetime.now(UTC)
    async with async_session() as s:
        pid = await f.seed_portfolio(s, name="micro-window", deposit=10_000, kind="micro")
        await f.seed_watchlist(s, "AAA")
        await f.seed_bars(s, "AAA", closes=[50, 50, 50], start=(now - dt.timedelta(days=3)).date())
        await f.seed_intraday_bars(
            s, "AAA", closes=[float(50 + i) for i in range(40)], start=now - dt.timedelta(hours=4)
        )
        await s.commit()

    await jobs.run_micro()
    assert await _orders(pid, "buy") == []


async def test_micro_eod_flatten_liquidates_micro_positions(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_near_market_close", lambda *_a, **_k: True)
    now = dt.datetime.now(UTC)
    async with async_session() as s:
        pid = await f.seed_portfolio(s, name="micro-flat", deposit=10_000, kind="micro")
        await f.seed_position(s, pid, "AAA", qty=10, avg_cost=50)
        await f.seed_intraday_bars(
            s, "AAA", closes=[55, 56], start=now - dt.timedelta(minutes=10)
        )
        await s.commit()

    await jobs.micro_eod_flatten()

    pos = await _position(pid, "AAA")
    assert pos is None or pos.qty == Decimal("0.000000")  # flat before the close
    sells = await _orders(pid, "sell")
    assert len(sells) == 1 and sells[0].status == "filled"


async def test_micro_eod_flatten_noop_when_not_near_close(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_near_market_close", lambda *_a, **_k: False)
    async with async_session() as s:
        pid = await f.seed_portfolio(s, name="micro-hold", deposit=10_000, kind="micro")
        await f.seed_position(s, pid, "AAA", qty=10, avg_cost=50)
        await s.commit()

    await jobs.micro_eod_flatten()
    pos = await _position(pid, "AAA")
    assert pos is not None and pos.qty == Decimal("10.000000")  # untouched mid-session
