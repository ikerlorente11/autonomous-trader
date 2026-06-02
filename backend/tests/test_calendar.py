"""Tests for market-calendar helpers (pure: pandas_market_calendars, no I/O).

Uses fixed, well-known NYSE 2026 dates so expectations are stable.
"""

from __future__ import annotations

import datetime as dt

from backend.data_ingestion import calendar as cal


def test_weekday_is_trading_day() -> None:
    # Monday 2026-01-05 is a regular session.
    assert cal.is_trading_day(dt.date(2026, 1, 5)) is True


def test_weekend_is_not_trading_day() -> None:
    # Saturday 2026-01-03.
    assert cal.is_trading_day(dt.date(2026, 1, 3)) is False


def test_new_year_holiday_is_not_trading_day() -> None:
    # New Year's Day 2026 (Thursday) — NYSE closed.
    assert cal.is_trading_day(dt.date(2026, 1, 1)) is False


def test_trading_days_range_excludes_weekend() -> None:
    days = cal.trading_days(dt.date(2026, 1, 5), dt.date(2026, 1, 11))
    # Mon-Fri only (5,6,7,8,9); weekend 10-11 excluded.
    assert days == [
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 6),
        dt.date(2026, 1, 7),
        dt.date(2026, 1, 8),
        dt.date(2026, 1, 9),
    ]


def test_previous_trading_day_skips_weekend() -> None:
    # Monday 2026-01-05 -> previous session is Friday 2026-01-02.
    assert cal.previous_trading_day(dt.date(2026, 1, 5)) == dt.date(2026, 1, 2)
