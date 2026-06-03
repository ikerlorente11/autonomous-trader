"""Macro ingestion end-to-end: FRED provider over respx + real test DB.

Covers provider fetch (happy + missing key), idempotent upsert, and the
fetch_macro_data job (success, no-key skip, market-closed skip)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx
import sqlalchemy as sa

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.macro_ingest import upsert_macro_series
from backend.data_ingestion.providers import fred_provider as fred
from backend.data_ingestion.providers.fred_provider import FredProvider
from backend.db.models import JobRun, MacroSeries
from backend.db.session import async_session
from backend.scheduler import jobs

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
_FRED_URL = r".*stlouisfed\.org/fred/series/observations.*"


def _fred_payload() -> dict:
    return {
        "observations": [
            {"date": "2026-05-28", "value": "0.40"},
            {"date": "2026-05-29", "value": "."},  # missing -> dropped
            {"date": "2026-06-01", "value": "0.45"},
        ]
    }


@pytest.fixture(autouse=True)
def _fast_fred(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(fred.asyncio, "sleep", _noop)
    monkeypatch.setenv("FRED_THROTTLE_MS", "0")


async def _latest_run(job: str) -> JobRun | None:
    async with async_session() as s:
        stmt = (
            sa.select(JobRun)
            .where(JobRun.job == job)
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        return (await s.scalars(stmt)).first()


async def _macro_count(series_id: str) -> int:
    async with async_session() as s:
        return await s.scalar(
            sa.select(sa.func.count())
            .select_from(MacroSeries)
            .where(MacroSeries.series_id == series_id)
        )


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
async def test_fetch_series_parses_and_drops_missing(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    respx_mock.get(url__regex=_FRED_URL).mock(
        return_value=httpx.Response(200, json=_fred_payload())
    )

    out = await FredProvider().fetch_series(
        ["T10Y2Y"], dt.date(2026, 5, 1), dt.date(2026, 6, 1)
    )

    assert out["T10Y2Y"] == [
        (dt.datetime(2026, 5, 28, tzinfo=UTC), Decimal("0.40")),
        (dt.datetime(2026, 6, 1, tzinfo=UTC), Decimal("0.45")),
    ]


async def test_fetch_series_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        await FredProvider().fetch_series(["T10Y2Y"], dt.date(2026, 5, 1), dt.date(2026, 6, 1))


# --------------------------------------------------------------------------- #
# Upsert idempotency
# --------------------------------------------------------------------------- #
async def test_upsert_macro_series_is_idempotent(db_session) -> None:
    obs = [
        (dt.datetime(2026, 5, 28, tzinfo=UTC), Decimal("0.40")),
        (dt.datetime(2026, 6, 1, tzinfo=UTC), Decimal("0.45")),
    ]
    assert await upsert_macro_series(db_session, "T10Y2Y", obs) == 2
    await upsert_macro_series(db_session, "T10Y2Y", obs)  # re-run: overwrite, no dup
    await db_session.flush()
    n = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(MacroSeries)
        .where(MacroSeries.series_id == "T10Y2Y")
    )
    assert n == 2


# --------------------------------------------------------------------------- #
# Job
# --------------------------------------------------------------------------- #
async def test_fetch_macro_data_writes_series_and_records_success(
    clean_db, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setenv("FRED_SERIES", "T10Y2Y")  # single series -> one request
    respx_mock.get(url__regex=_FRED_URL).mock(
        return_value=httpx.Response(200, json=_fred_payload())
    )

    await jobs.fetch_macro_data()

    assert await _macro_count("T10Y2Y") == 2
    run = await _latest_run("fetch_macro_data")
    assert run is not None and run.status == "success"


async def test_fetch_macro_data_skips_without_key(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    await jobs.fetch_macro_data()

    run = await _latest_run("fetch_macro_data")
    assert run is not None and run.status == "skipped"
    assert run.detail == {"reason": "no_api_key"}


async def test_fetch_macro_data_skips_when_market_closed(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: False)

    await jobs.fetch_macro_data()

    run = await _latest_run("fetch_macro_data")
    assert run is not None and run.status == "skipped"
