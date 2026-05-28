"""Market-calendar helpers.

The scheduler asks this module "is today a trading day?" before spending API quota,
and the validation layer asks "which sessions *should* exist in this range?" to detect
gaps. Exchange selection is env-driven (``MARKET_CALENDAR``, default NYSE) so the
universe is never hardcoded.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas_market_calendars as mcal

_DEFAULT_CALENDAR = "NYSE"


def _calendar_name() -> str:
    return os.environ.get("MARKET_CALENDAR", _DEFAULT_CALENDAR)


def trading_days(start: dt.date, end: dt.date, *, calendar: str | None = None) -> list[dt.date]:
    """All exchange sessions in ``[start, end]`` (inclusive), ascending."""
    cal = mcal.get_calendar(calendar or _calendar_name())
    schedule = cal.schedule(start_date=start, end_date=end)
    return [ts.date() for ts in schedule.index]


def is_trading_day(day: dt.date, *, calendar: str | None = None) -> bool:
    """True if ``day`` is a full exchange session (not weekend/holiday)."""
    return day in set(trading_days(day, day, calendar=calendar))


def previous_trading_day(day: dt.date, *, calendar: str | None = None) -> dt.date:
    """The most recent session strictly before ``day``."""
    window_start = day - dt.timedelta(days=10)
    sessions = trading_days(window_start, day - dt.timedelta(days=1), calendar=calendar)
    if not sessions:
        raise ValueError(f"no trading session found in 10 days before {day.isoformat()}")
    return sessions[-1]
