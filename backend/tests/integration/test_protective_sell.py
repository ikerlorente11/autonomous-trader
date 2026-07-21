"""protective_sell job end-to-end: real test DB + mocked live prices (respx)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx
import sqlalchemy as sa

from backend.data_ingestion.providers import yfinance_provider as yf
from backend.db.models import JobRun, PortfolioPosition, TradeOrder
from backend.db.session import async_session
from backend.scheduler import jobs
from backend.tests import factories as f

pytestmark = pytest.mark.integration


def _live_payload(price: float) -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price}}], "error": None}}


def _route(respx_mock: respx.MockRouter, symbol: str):
    return respx_mock.get(url__regex=rf".*/chart/{symbol}(\?.*)?$")


@pytest.fixture(autouse=True)
def _fast_open(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(yf.asyncio, "sleep", _noop)
    monkeypatch.setenv("YFINANCE_THROTTLE_MS", "0")
    monkeypatch.setenv("TRAILING_STOP_PCT", "0.08")
    monkeypatch.setenv("PROTECTIVE_SELL_ENABLED", "true")
    # Default: regime off (no live ^VIX fetch); ATR off unless a test seeds bars + multiple.
    monkeypatch.setenv("STOP_REGIME_ENABLED", "false")
    monkeypatch.setenv("STOP_ATR_MULTIPLE", "0")
    # Pretend the market is open so the job acts regardless of wall-clock.
    monkeypatch.setattr(jobs, "is_market_open_now", lambda: True)


async def _seed(symbol: str, *, qty: float, avg_cost: float, hwm: float | None) -> int:
    async with async_session() as s:
        pid = await f.seed_portfolio(s, deposit=100_000)
        await f.seed_position(s, pid, symbol, qty=qty, avg_cost=avg_cost, high_water_mark=hwm)
        await s.commit()
        return pid


async def _latest_run() -> JobRun | None:
    async with async_session() as s:
        stmt = (
            sa.select(JobRun)
            .where(JobRun.job == "protective_sell")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        return (await s.scalars(stmt)).first()


async def test_stop_triggers_and_sells_full_position(
    clean_db, respx_mock: respx.MockRouter
) -> None:
    pid = await _seed("AAPL", qty=10, avg_cost=100, hwm=130)
    # live 119 <= peak 130 * 0.92 = 119.6 -> trigger
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_live_payload(119.0)))

    await jobs.protective_sell()

    async with async_session() as s:
        pos = await s.get(PortfolioPosition, (pid, "AAPL"))
        sells = (
            await s.scalars(
                sa.select(TradeOrder).where(
                    TradeOrder.portfolio_id == pid,
                    sa.func.lower(TradeOrder.side) == "sell",
                )
            )
        ).all()
    assert pos.qty == Decimal("0.000000")           # liquidated in full
    assert len(sells) == 1
    assert sells[0].strategy_version == "protective-sell"
    run = await _latest_run()
    assert run.status == "success" and run.detail["stops_triggered"] == 1


async def test_no_trigger_holds_and_ratchets_high_water_mark(
    clean_db, respx_mock: respx.MockRouter
) -> None:
    pid = await _seed("AAPL", qty=10, avg_cost=100, hwm=120)
    # live 135 > peak -> no trigger, and hwm ratchets up to 135
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_live_payload(135.0)))

    await jobs.protective_sell()

    async with async_session() as s:
        pos = await s.get(PortfolioPosition, (pid, "AAPL"))
        sells = (
            await s.scalars(
                sa.select(TradeOrder).where(sa.func.lower(TradeOrder.side) == "sell")
            )
        ).all()
    assert pos.qty == Decimal("10.000000")          # untouched
    assert pos.high_water_mark == Decimal("135.000000")  # ratcheted up
    assert sells == []
    run = await _latest_run()
    assert run.detail["stops_triggered"] == 0


async def test_atr_stop_triggers_where_pct_would_not(
    clean_db, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOP_ATR_MULTIPLE", "2.5")  # ATR mode on for this test
    async with async_session() as s:
        pid = await f.seed_portfolio(s, deposit=100_000)
        await f.seed_position(s, pid, "AAPL", qty=10, avg_cost=100, high_water_mark=None)
        # 20 flat bars with a daily range of 2 -> ATR(14) ~ 2.0. Seeded relative to
        # today: the job only reads bars inside its _ATR_LOOKBACK_DAYS window, so a
        # fixed start date rots as the calendar advances (ATR silently falls back
        # to the pct stop and the assertion flips).
        await f.seed_bars(
            s, "AAPL", closes=[100.0] * 20,
            start=dt.date.today() - dt.timedelta(days=25),
        )
        await s.commit()
    # live 94: ATR distance 2.5*2=5 -> threshold 95 -> SELL; pct 8% threshold 92 -> would hold
    _route(respx_mock, "AAPL").mock(return_value=httpx.Response(200, json=_live_payload(94.0)))

    await jobs.protective_sell()

    async with async_session() as s:
        pos = await s.get(PortfolioPosition, (pid, "AAPL"))
    assert pos.qty == Decimal("0.000000")  # ATR-based stop fired


async def test_skips_when_market_closed(clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "is_market_open_now", lambda: False)
    await _seed("AAPL", qty=10, avg_cost=100, hwm=130)

    await jobs.protective_sell()

    run = await _latest_run()
    assert run is not None and run.status == "skipped"
    assert run.detail["reason"] == "MARKET_CLOSED"
