"""Tests for the pure data-quality validation layer."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.contracts import OHLCVBar
from backend.data_ingestion import validation as v


def _bar(day: dt.date, close: float) -> OHLCVBar:
    c = Decimal(str(close))
    return OHLCVBar(
        symbol="AAA",
        ts=dt.datetime(day.year, day.month, day.day),
        open=c,
        high=c,
        low=c,
        close=c,
        volume=1000,
        adj_close=c,
    )


def test_detect_missing_days_flags_gap() -> None:
    # 2026-01-05..09 are sessions; provide only Mon and Fri.
    bars = [_bar(dt.date(2026, 1, 5), 100), _bar(dt.date(2026, 1, 9), 100)]
    missing = v.detect_missing_days(bars, dt.date(2026, 1, 5), dt.date(2026, 1, 9))
    assert missing == [dt.date(2026, 1, 6), dt.date(2026, 1, 7), dt.date(2026, 1, 8)]


def test_detect_missing_days_none_when_complete() -> None:
    bars = [_bar(dt.date(2026, 1, d), 100) for d in (5, 6, 7, 8, 9)]
    assert v.detect_missing_days(bars, dt.date(2026, 1, 5), dt.date(2026, 1, 9)) == []


def test_detect_price_anomaly_over_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_ANOMALY_PCT", "0.50")
    bars = [_bar(dt.date(2026, 1, 5), 100), _bar(dt.date(2026, 1, 6), 200)]  # +100%
    anomalies = v.detect_price_anomalies("AAA", bars)
    assert len(anomalies) == 1
    assert anomalies[0].pct_change == Decimal("1.0")


def test_detect_price_anomaly_within_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_ANOMALY_PCT", "0.50")
    bars = [_bar(dt.date(2026, 1, 5), 100), _bar(dt.date(2026, 1, 6), 120)]  # +20%
    assert v.detect_price_anomalies("AAA", bars) == []


def test_detect_stale_returns_none_when_fresh() -> None:
    bars = [_bar(dt.date(2026, 1, d), 100) for d in (5, 6, 7, 8, 9)]
    assert v.detect_stale(bars, asof=dt.date(2026, 1, 9)) is None


def test_detect_stale_flags_old_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_STALE_MAX_AGE_DAYS", "1")
    bars = [_bar(dt.date(2026, 1, 5), 100)]
    stale = v.detect_stale(bars, asof=dt.date(2026, 1, 9))
    assert stale == dt.date(2026, 1, 5)


def test_validate_batch_empty_symbol_marks_not_ok() -> None:
    report = v.validate_batch(
        {"AAA": []}, ["AAA"], dt.date(2026, 1, 5), dt.date(2026, 1, 9)
    )
    assert report.empty_symbols == ["AAA"]
    assert report.ok is False


def test_validate_batch_clean_is_ok() -> None:
    bars = [_bar(dt.date(2026, 1, d), 100) for d in (5, 6, 7, 8, 9)]
    report = v.validate_batch(
        {"AAA": bars}, ["AAA"], dt.date(2026, 1, 5), dt.date(2026, 1, 9),
        asof=dt.date(2026, 1, 9),
    )
    assert report.ok is True
    assert report.anomalies == []
