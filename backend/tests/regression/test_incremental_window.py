"""Regression: the incremental OHLCV fetch must use a trailing window, not today..today.

Bug (2026-06-01): the `current` group fetched ``today..today``. The job runs at 06:30
UTC — before the US session opens — so 'today' has no settled daily bar yet, and the
fetch returned empty for every symbol → the job failed daily (masked by a Twelve Data
rate-limit error). Fixed by requesting ``today - _INCREMENTAL_LOOKBACK_DAYS .. today``.

DB-free: every collaborator of fetch_market_data is stubbed so this runs in the fast
pre-push suite and asserts purely on the date range handed to ingest."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.scheduler import jobs

pytestmark = [pytest.mark.regression, pytest.mark.unit]


class _NullSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def add(self, *_a):
        pass

    async def commit(self):
        pass


class _Row:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _Report:
    empty_symbols: list[str] = []
    anomalies: list = []


async def test_current_group_fetches_a_trailing_window(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], dt.date, dt.date]] = []

    async def _fake_ingest(session, symbols, start, end):
        calls.append((tuple(symbols), start, end))
        return _Report()

    async def _fake_watchlist(session):
        return [_Row("AAPL")]

    async def _fake_counts(session, symbols, start, end):
        return {"AAPL": 100}  # >= _MIN_HISTORY_BARS -> the incremental ("current") path

    async def _fake_coverage(session, symbols, start, end):
        # Every session complete: nothing to heal, so the trailing window stands.
        days = jobs.trading_days(start.date(), end.date())
        return {day: len(symbols) for day in days}

    monkeypatch.setattr(jobs, "ingest_daily_bars", _fake_ingest)
    monkeypatch.setattr(jobs, "get_active_watchlist", _fake_watchlist)
    monkeypatch.setattr(jobs, "count_bars_per_symbol", _fake_counts)
    monkeypatch.setattr(jobs, "bar_coverage_by_session", _fake_coverage)
    monkeypatch.setattr(jobs, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(jobs, "async_session", lambda: _NullSession())

    await jobs.fetch_market_data()

    assert len(calls) == 1, "only the current group should fetch"
    symbols, start, end = calls[0]
    today = dt.date.today()
    assert symbols == ("AAPL",)
    assert end == today
    assert start == today - dt.timedelta(days=jobs._INCREMENTAL_LOOKBACK_DAYS)
    assert start < end, "regression: a single today..today day has no settled bar"
