"""fetch_market_data end-to-end: real test DB + mocked Yahoo (respx)."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx
import sqlalchemy as sa

from backend.data_ingestion.providers import yfinance_provider as yf
from backend.db.models import JobRun, MarketBar
from backend.db.queries.portfolio_queries import upsert_watchlist_symbol
from backend.db.session import async_session
from backend.scheduler import jobs

pytestmark = pytest.mark.integration

_EPOCH = int(dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc).timestamp())


def _yahoo_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [_EPOCH],
                    "indicators": {
                        "quote": [{"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [1000]}],
                        "adjclose": [{"adjclose": [10.5]}],
                    },
                }
            ],
            "error": None,
        }
    }


@pytest.fixture(autouse=True)
def _fast_yf(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(yf.asyncio, "sleep", _noop)
    monkeypatch.setenv("YFINANCE_THROTTLE_MS", "0")


async def _seed_watchlist(*symbols: str) -> None:
    async with async_session() as s:
        for sym in symbols:
            await upsert_watchlist_symbol(s, sym)
        await s.commit()


async def _latest_run(job: str) -> JobRun | None:
    async with async_session() as s:
        stmt = sa.select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1)
        return (await s.scalars(stmt)).first()


async def test_fetch_market_data_writes_bars_and_records_success(
    clean_db, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pin the calendar open: the job is market-day-gated, so without this the test
    # would skip (and fail the bar assertion) whenever it runs on a weekend/holiday.
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    await _seed_watchlist("AAPL")
    respx_mock.get(url__regex=r".*/chart/AAPL(\?.*)?$").mock(
        return_value=httpx.Response(200, json=_yahoo_payload())
    )

    await jobs.fetch_market_data()

    async with async_session() as s:
        n = await s.scalar(sa.select(sa.func.count()).select_from(MarketBar).where(MarketBar.symbol == "AAPL"))
    assert n >= 1
    run = await _latest_run("fetch_market_data")
    assert run is not None and run.status in ("success", "degraded")


async def test_fetch_market_data_skips_when_market_closed(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: False)
    await _seed_watchlist("AAPL")

    await jobs.fetch_market_data()

    run = await _latest_run("fetch_market_data")
    assert run is not None and run.status == "skipped"
