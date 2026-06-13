"""is_market_open_now / is_near_market_close — NYSE intraday session detection."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion.calendar import is_market_open_now, is_near_market_close

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _at(y, m, d, hh, mm) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


def test_open_during_regular_session() -> None:
    # 2026-06-01 is a Monday; NYSE 09:30–16:00 ET = 13:30–20:00 UTC (EDT).
    assert is_market_open_now(now=_at(2026, 6, 1, 15, 0)) is True


def test_closed_before_open() -> None:
    assert is_market_open_now(now=_at(2026, 6, 1, 6, 30)) is False  # pre-market (06:30 UTC)


def test_closed_after_close() -> None:
    assert is_market_open_now(now=_at(2026, 6, 1, 21, 0)) is False  # after 20:00 UTC


def test_closed_on_weekend() -> None:
    assert is_market_open_now(now=_at(2026, 5, 30, 15, 0)) is False  # Saturday


def test_closed_on_holiday() -> None:
    assert is_market_open_now(now=_at(2026, 5, 25, 15, 0)) is False  # Memorial Day


# 2026-06-01 Monday: NYSE close = 20:00 UTC (EDT). within=10 → act from 19:50 UTC.
def test_near_close_within_window() -> None:
    assert is_near_market_close(10, now=_at(2026, 6, 1, 19, 55)) is True


def test_not_near_close_mid_session() -> None:
    assert is_near_market_close(10, now=_at(2026, 6, 1, 17, 0)) is False


def test_not_near_close_after_close() -> None:
    assert is_near_market_close(10, now=_at(2026, 6, 1, 20, 5)) is False


def test_not_near_close_on_weekend() -> None:
    assert is_near_market_close(10, now=_at(2026, 5, 30, 19, 55)) is False
