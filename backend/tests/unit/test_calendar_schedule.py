"""Market-calendar helpers and the job-schedule next-run math."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion.calendar import (
    is_trading_day,
    previous_trading_day,
    trading_days,
)
from backend.scheduler.schedule import next_run_after

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def test_is_trading_day_weekday_true_weekend_false() -> None:
    assert is_trading_day(dt.date(2026, 5, 29)) is True   # Friday
    assert is_trading_day(dt.date(2026, 5, 30)) is False  # Saturday


def test_is_trading_day_us_holiday_false() -> None:
    assert is_trading_day(dt.date(2026, 5, 25)) is False  # Memorial Day 2026


def test_previous_trading_day_skips_weekend() -> None:
    # Monday 2026-06-01 -> previous session is Friday 2026-05-29
    assert previous_trading_day(dt.date(2026, 6, 1)) == dt.date(2026, 5, 29)


def test_trading_days_inclusive_ascending() -> None:
    days = trading_days(dt.date(2026, 6, 1), dt.date(2026, 6, 5))
    assert days == sorted(days)
    assert days[0] == dt.date(2026, 6, 1) and days[-1] == dt.date(2026, 6, 5)


def test_next_run_after_same_day_when_before_slot() -> None:
    now = dt.datetime(2026, 6, 1, 5, 0, tzinfo=UTC)  # before 06:30
    nxt = next_run_after("fetch_market_data", now)
    assert nxt == dt.datetime(2026, 6, 1, 6, 30, tzinfo=UTC)


def test_next_run_after_rolls_to_tomorrow_when_past_slot() -> None:
    now = dt.datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # after 08:00
    nxt = next_run_after("execute_paper_trades", now)
    assert nxt == dt.datetime(2026, 6, 2, 8, 0, tzinfo=UTC)


def test_next_run_after_unknown_job_is_none() -> None:
    assert next_run_after("nope", dt.datetime(2026, 6, 1, tzinfo=UTC)) is None
