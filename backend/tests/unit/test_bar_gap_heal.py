"""Self-healing incremental fetch: an incomplete past session widens the window.

Regression for the 2026-08-04 blackout, whose lost sessions (Aug 4-6 empty, Aug 3 at
1/62 symbols) survived forever because the fixed 5-day trailing window had already
moved past them by the time the scheduler came back."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.scheduler import jobs

pytestmark = pytest.mark.unit

SYMBOLS = ["AAA", "BBB"]
# 2026-08-31 is a Monday; the sessions below are Mon 08-24 .. Fri 08-28.
TODAY = dt.date(2026, 8, 31)


def _patch_coverage(monkeypatch: pytest.MonkeyPatch, coverage: dict[dt.date, int]) -> None:
    async def _fake(session, symbols, start, end):  # noqa: ANN001 - test double
        return coverage

    monkeypatch.setattr(jobs, "bar_coverage_by_session", _fake)


def _full(days: list[dt.date]) -> dict[dt.date, int]:
    return {day: len(SYMBOLS) for day in days}


def _expected_sessions() -> list[dt.date]:
    window_start = TODAY - dt.timedelta(days=jobs._GAP_HEAL_LOOKBACK_DAYS)
    return jobs.trading_days(window_start, jobs.previous_trading_day(TODAY))[:-1]


async def test_no_gap_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_coverage(monkeypatch, _full(_expected_sessions()))
    assert await jobs._oldest_incomplete_session(None, SYMBOLS, TODAY) is None


async def test_missing_session_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _expected_sessions()
    coverage = _full(sessions)
    del coverage[sessions[10]]
    _patch_coverage(monkeypatch, coverage)
    assert await jobs._oldest_incomplete_session(None, SYMBOLS, TODAY) == sessions[10]


async def test_partial_session_counts_as_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _expected_sessions()
    coverage = _full(sessions)
    coverage[sessions[3]] = 1  # the Aug-3 shape: one symbol stored, the rest lost
    _patch_coverage(monkeypatch, coverage)
    assert await jobs._oldest_incomplete_session(None, SYMBOLS, TODAY) == sessions[3]


async def test_oldest_gap_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _expected_sessions()
    coverage = _full(sessions)
    del coverage[sessions[2]]
    del coverage[sessions[9]]
    _patch_coverage(monkeypatch, coverage)
    assert await jobs._oldest_incomplete_session(None, SYMBOLS, TODAY) == sessions[2]


async def test_newest_session_never_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    # The job runs pre-market: the latest close is what this very run will fetch.
    sessions = jobs.trading_days(
        TODAY - dt.timedelta(days=jobs._GAP_HEAL_LOOKBACK_DAYS),
        jobs.previous_trading_day(TODAY),
    )
    coverage = _full(sessions[:-1])
    _patch_coverage(monkeypatch, coverage)
    assert await jobs._oldest_incomplete_session(None, SYMBOLS, TODAY) is None
