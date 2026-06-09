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


def is_market_open_now(
    *, calendar: str | None = None, now: dt.datetime | None = None
) -> bool:
    """True if the exchange is in a regular session at ``now`` (UTC; defaults to wall-clock).

    Used by the intraday protective-sell job so it only acts while the market trades.
    ``now`` is injectable for tests."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    cal = mcal.get_calendar(calendar or _calendar_name())
    schedule = cal.schedule(start_date=moment.date(), end_date=moment.date())
    if schedule.empty:
        return False
    open_ts = schedule.iloc[0]["market_open"].to_pydatetime()
    close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_ts <= moment <= close_ts


def previous_trading_day(day: dt.date, *, calendar: str | None = None) -> dt.date:
    """The most recent session strictly before ``day``."""
    window_start = day - dt.timedelta(days=10)
    sessions = trading_days(window_start, day - dt.timedelta(days=1), calendar=calendar)
    if not sessions:
        raise ValueError(f"no trading session found in 10 days before {day.isoformat()}")
    return sessions[-1]


def nth_prior_trading_day(
    day: dt.date, n: int, *, calendar: str | None = None
) -> dt.date | None:
    """The session ``n`` trading days before ``day`` (excluding ``day`` itself).

    The data-freshness gate (P12) uses this as the staleness cutoff: a symbol whose
    latest bar predates this date has missed more than ``n`` sessions. Returns ``None``
    when ``n <= 0`` (gate disabled) or there is not enough calendar history to judge."""
    if n <= 0:
        return None
    window_start = day - dt.timedelta(days=n * 3 + 10)
    sessions = [d for d in trading_days(window_start, day, calendar=calendar) if d < day]
    if len(sessions) < n:
        return None
    return sessions[-n]
