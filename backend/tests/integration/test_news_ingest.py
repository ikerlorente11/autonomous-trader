"""News ingestion end-to-end: Finnhub provider over respx + real test DB."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx
import sqlalchemy as sa

from backend.data_ingestion.errors import ProviderError
from backend.data_ingestion.news_ingest import upsert_news_sentiment
from backend.data_ingestion.providers import finnhub_news_provider as fh
from backend.data_ingestion.providers.finnhub_news_provider import FinnhubNewsProvider
from backend.db.models import JobRun, NewsSentiment
from backend.db.queries.portfolio_queries import upsert_watchlist_symbol
from backend.db.session import async_session
from backend.scheduler import jobs

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
_NEWS_URL = r".*finnhub\.io/api/v1/company-news.*"


def _epoch(y: int, m: int, d: int, h: int = 12) -> int:
    return int(dt.datetime(y, m, d, h, tzinfo=UTC).timestamp())


def _finnhub_payload() -> list[dict]:
    return [
        {"datetime": _epoch(2026, 5, 28, 9), "headline": "a"},
        {"datetime": _epoch(2026, 5, 28, 20), "headline": "b"},  # same day -> 2
        {"datetime": _epoch(2026, 5, 29, 11), "headline": "c"},
    ]


@pytest.fixture(autouse=True)
def _fast_finnhub(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(fh.asyncio, "sleep", _noop)
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


async def _news_count(symbol: str) -> int:
    async with async_session() as s:
        return await s.scalar(
            sa.select(sa.func.count())
            .select_from(NewsSentiment)
            .where(NewsSentiment.symbol == symbol)
        )


async def _seed_watchlist(*symbols: str) -> None:
    async with async_session() as s:
        for sym in symbols:
            await upsert_watchlist_symbol(s, sym)
        await s.commit()


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
async def test_fetch_aggregates_daily_counts(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    respx_mock.get(url__regex=_NEWS_URL).mock(
        return_value=httpx.Response(200, json=_finnhub_payload())
    )

    out = await FinnhubNewsProvider().fetch_news_sentiment(
        ["AAPL"], dt.datetime(2026, 5, 1, tzinfo=UTC)
    )

    counts = {int(e["ts"]): int(e["article_count"]) for e in out["AAPL"]}
    assert counts == {
        int(dt.datetime(2026, 5, 28, tzinfo=UTC).timestamp()): 2,
        int(dt.datetime(2026, 5, 29, tzinfo=UTC).timestamp()): 1,
    }


async def test_fetch_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        await FinnhubNewsProvider().fetch_news_sentiment(
            ["AAPL"], dt.datetime(2026, 5, 1, tzinfo=UTC)
        )


# --------------------------------------------------------------------------- #
# Upsert idempotency
# --------------------------------------------------------------------------- #
async def test_upsert_news_is_idempotent(db_session) -> None:
    entries = [
        {"ts": float(_epoch(2026, 5, 28, 0)), "article_count": 2.0},
        {"ts": float(_epoch(2026, 5, 29, 0)), "article_count": 1.0},
    ]
    assert await upsert_news_sentiment(db_session, "AAPL", entries) == 2
    await upsert_news_sentiment(db_session, "AAPL", entries)  # re-run: overwrite
    await db_session.flush()
    n = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NewsSentiment)
        .where(NewsSentiment.symbol == "AAPL")
    )
    assert n == 2


# --------------------------------------------------------------------------- #
# Job
# --------------------------------------------------------------------------- #
async def test_fetch_news_writes_rows_and_records_success(
    clean_db, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    await _seed_watchlist("AAPL")
    respx_mock.get(url__regex=_NEWS_URL).mock(
        return_value=httpx.Response(200, json=_finnhub_payload())
    )

    await jobs.fetch_news_sentiment()

    assert await _news_count("AAPL") == 2  # two distinct days
    run = await _latest_run("fetch_news_sentiment")
    assert run is not None and run.status == "success"


async def test_fetch_news_skips_without_key(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    await _seed_watchlist("AAPL")

    await jobs.fetch_news_sentiment()

    run = await _latest_run("fetch_news_sentiment")
    assert run is not None and run.status == "skipped"
    assert run.detail == {"reason": "no_api_key"}


async def test_fetch_news_skips_when_market_closed(
    clean_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: False)

    await jobs.fetch_news_sentiment()

    run = await _latest_run("fetch_news_sentiment")
    assert run is not None and run.status == "skipped"
