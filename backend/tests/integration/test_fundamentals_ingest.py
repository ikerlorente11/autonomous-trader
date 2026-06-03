"""Fundamentals ingestion end-to-end: Finnhub provider over respx + real test DB."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx
import sqlalchemy as sa

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.fundamentals_ingest import upsert_fundamentals_quarterly
from backend.data_ingestion.providers import finnhub_fundamentals_provider as ff
from backend.data_ingestion.providers.finnhub_fundamentals_provider import (
    FinnhubFundamentalsProvider,
)
from backend.db.models import FundamentalsQuarterly, JobRun
from backend.db.queries.portfolio_queries import upsert_watchlist_symbol
from backend.db.session import async_session
from backend.scheduler import jobs

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
_URL = r".*finnhub\.io/api/v1/stock/financials-reported.*"


def _payload() -> dict:
    return {
        "symbol": "AAPL",
        "data": [
            {
                "year": 2025,
                "quarter": 2,
                "endDate": "2025-06-30 00:00:00",
                "report": {
                    "ic": [
                        {"concept": "us-gaap_Revenues", "value": 180.0},
                        {"concept": "us-gaap_NetIncomeLoss", "value": 20.0},
                        {"concept": "us-gaap_GrossProfit", "value": 100.0},
                    ],
                    "bs": [{"concept": "us-gaap_StockholdersEquity", "value": 130.0}],
                    "cf": [
                        {"concept": "us-gaap_NetCashProvidedByUsedInOperatingActivities", "value": 30.0},
                        {"concept": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "value": 8.0},
                    ],
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def _fast_finnhub(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(ff.asyncio, "sleep", _noop)
    monkeypatch.setenv("FINNHUB_THROTTLE_MS", "0")


async def _latest_run(job: str) -> JobRun | None:
    async with async_session() as s:
        stmt = (
            sa.select(JobRun)
            .where(JobRun.job == job)
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        return (await s.scalars(stmt)).first()


async def _seed_watchlist(*symbols: str) -> None:
    async with async_session() as s:
        for sym in symbols:
            await upsert_watchlist_symbol(s, sym)
        await s.commit()


async def test_fetch_parses_quarterly_statements(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=_payload()))

    out = await FinnhubFundamentalsProvider().fetch_quarterly_statements(["AAPL"])

    assert len(out["AAPL"]) == 1
    statement = out["AAPL"][0]
    assert statement["revenue"] == 180.0
    assert statement["free_cash_flow"] == pytest.approx(22.0)


async def test_fetch_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        await FinnhubFundamentalsProvider().fetch_quarterly_statements(["AAPL"])


async def test_upsert_fundamentals_is_idempotent(db_session) -> None:
    epoch = float(dt.datetime(2025, 6, 30, tzinfo=UTC).timestamp())
    statements = [{"period_end": epoch, "revenue": 180.0, "net_income": 20.0}]
    assert await upsert_fundamentals_quarterly(db_session, "AAPL", statements) == 1
    await upsert_fundamentals_quarterly(db_session, "AAPL", statements)  # overwrite
    await db_session.flush()
    n = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(FundamentalsQuarterly)
        .where(FundamentalsQuarterly.symbol == "AAPL")
    )
    assert n == 1


async def test_upsert_dedupes_duplicate_period_ends(db_session) -> None:
    # Two reports for the same period_end (e.g. 10-Q then a fuller 10-K) must not
    # trip ON CONFLICT; keep the most complete row.
    epoch = float(dt.datetime(2025, 6, 30, tzinfo=UTC).timestamp())
    statements = [
        {"period_end": epoch, "revenue": 180.0},
        {"period_end": epoch, "revenue": 180.0, "net_income": 20.0, "equity": 130.0},
    ]
    assert await upsert_fundamentals_quarterly(db_session, "AAPL", statements) == 1
    await db_session.flush()
    row = await db_session.scalar(
        sa.select(FundamentalsQuarterly).where(FundamentalsQuarterly.symbol == "AAPL")
    )
    assert row is not None
    assert set(row.line_items) == {"revenue", "net_income", "equity"}  # fuller kept


async def test_fetch_fundamentals_job_writes_and_records_success(
    clean_db, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    await _seed_watchlist("AAPL")
    respx_mock.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=_payload()))

    await jobs.fetch_fundamentals()

    async with async_session() as s:
        n = await s.scalar(
            sa.select(sa.func.count())
            .select_from(FundamentalsQuarterly)
            .where(FundamentalsQuarterly.symbol == "AAPL")
        )
    assert n == 1
    run = await _latest_run("fetch_fundamentals")
    assert run is not None and run.status == "success"


async def test_fetch_fundamentals_skips_without_key(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    await _seed_watchlist("AAPL")

    await jobs.fetch_fundamentals()

    run = await _latest_run("fetch_fundamentals")
    assert run is not None and run.status == "skipped"
    assert run.detail == {"reason": "no_api_key"}


async def test_fetch_fundamentals_skips_when_market_closed(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: False)

    await jobs.fetch_fundamentals()

    run = await _latest_run("fetch_fundamentals")
    assert run is not None and run.status == "skipped"
