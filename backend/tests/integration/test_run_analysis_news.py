"""run_analysis news-buzz observation: records the news_buzz signal_value from
ingested daily article counts without altering the composite score."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from backend.analysis.signals.sentiment.news import NEWS_BUZZ_SIGNAL_ID
from backend.db.models import NewsSentiment, SignalValue
from backend.db.session import async_session
from backend.scheduler import jobs
from backend.tests import factories as f

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
_SYMBOL = "AAPL"
_CLOSES = [100.0 + i * 0.5 for i in range(60)]
_DAILY_COUNTS = [1, 1, 2, 1, 12]  # a spike on the latest day


@pytest.fixture(autouse=True)
def _trading_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)


async def _seed() -> None:
    start = dt.date.today() - dt.timedelta(days=70)
    base = jobs._today_utc_midnight() - dt.timedelta(days=len(_DAILY_COUNTS))
    async with async_session() as s:
        await f.seed_watchlist(s, _SYMBOL)
        await f.seed_bars(s, _SYMBOL, closes=_CLOSES, start=start)
        for i, count in enumerate(_DAILY_COUNTS):
            s.add(
                NewsSentiment(
                    symbol=_SYMBOL,
                    ts=base + dt.timedelta(days=i),
                    article_count=count,
                )
            )
        await s.commit()


async def test_records_news_buzz_signal(clean_db) -> None:
    await _seed()

    await jobs.run_analysis()

    async with async_session() as s:
        value = await s.scalar(
            sa.select(SignalValue.value).where(
                SignalValue.symbol == _SYMBOL,
                SignalValue.signal_id == NEWS_BUZZ_SIGNAL_ID,
            )
        )
    assert value is not None
    assert float(value) > 80.0  # spike on the latest day
