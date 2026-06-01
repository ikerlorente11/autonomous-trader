"""Post-fetch data-quality checks — pure functions over OHLCV bars."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.data_ingestion.calendar import trading_days
from backend.data_ingestion.validation import (
    detect_missing_days,
    detect_price_anomalies,
    detect_stale,
    validate_batch,
)
from backend.tests.factories import bar

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _bar_on(symbol: str, day: dt.date, close: float = 100.0):
    return bar(symbol, ts=dt.datetime(day.year, day.month, day.day, tzinfo=UTC), close=close)


def test_detect_missing_days_full_week_has_no_gaps() -> None:
    start, end = dt.date(2026, 6, 1), dt.date(2026, 6, 5)  # Mon–Fri, all sessions
    sessions = trading_days(start, end)
    bars = [_bar_on("AAPL", d) for d in sessions]
    assert detect_missing_days(bars, start, end) == []


def test_detect_missing_days_reports_the_gap() -> None:
    start, end = dt.date(2026, 6, 1), dt.date(2026, 6, 5)
    sessions = trading_days(start, end)
    bars = [_bar_on("AAPL", d) for d in sessions if d != dt.date(2026, 6, 3)]
    assert detect_missing_days(bars, start, end) == [dt.date(2026, 6, 3)]


def test_price_anomaly_flags_large_jump_only() -> None:
    bars = [
        _bar_on("AAPL", dt.date(2026, 5, 27), close=100),
        _bar_on("AAPL", dt.date(2026, 5, 28), close=210),  # +110% -> anomaly
        _bar_on("AAPL", dt.date(2026, 5, 29), close=215),  # +2.4% -> fine
    ]
    anomalies = detect_price_anomalies("AAPL", bars)
    assert len(anomalies) == 1
    assert anomalies[0].close == Decimal("210")
    assert anomalies[0].pct_change > Decimal("0.5")


def test_detect_stale_returns_last_date_when_old() -> None:
    old = [_bar_on("AAPL", dt.date(2026, 5, 1))]
    assert detect_stale(old, asof=dt.date(2026, 6, 1)) == dt.date(2026, 5, 1)


def test_detect_stale_none_when_fresh() -> None:
    fresh = [_bar_on("AAPL", d) for d in trading_days(dt.date(2026, 5, 26), dt.date(2026, 5, 29))]
    assert detect_stale(fresh, asof=dt.date(2026, 5, 29)) is None


def test_validate_batch_collects_empty_symbols_and_ok_flag() -> None:
    report = validate_batch(
        {"AAPL": [_bar_on("AAPL", dt.date(2026, 6, 1))], "MSFT": []},
        requested=["AAPL", "MSFT"],
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 6, 1),
    )
    assert report.empty_symbols == ["MSFT"]
    assert report.ok is False
