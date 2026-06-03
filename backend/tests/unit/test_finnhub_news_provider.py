"""Finnhub news provider — pure aggregation helpers, no network."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.data_ingestion.providers.finnhub_news_provider import (
    FinnhubNewsProvider,
    _counts_by_day,
    _day_epoch_utc,
)

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _epoch(y: int, m: int, d: int, h: int = 12) -> int:
    return int(dt.datetime(y, m, d, h, tzinfo=UTC).timestamp())


def test_day_epoch_normalizes_to_midnight_utc() -> None:
    midnight = int(dt.datetime(2026, 5, 28, tzinfo=UTC).timestamp())
    assert _day_epoch_utc(_epoch(2026, 5, 28, 18)) == midnight
    assert _day_epoch_utc("not-a-number") is None
    assert _day_epoch_utc(None) is None


def test_counts_by_day_aggregates_and_skips_bad_entries() -> None:
    articles = [
        {"datetime": _epoch(2026, 5, 28, 9)},
        {"datetime": _epoch(2026, 5, 28, 20)},  # same day -> count 2
        {"datetime": _epoch(2026, 5, 29, 11)},
        {"headline": "no datetime"},  # skipped
        "garbage",  # skipped
    ]
    counts = _counts_by_day(articles)
    assert counts == {
        int(dt.datetime(2026, 5, 28, tzinfo=UTC).timestamp()): 2,
        int(dt.datetime(2026, 5, 29, tzinfo=UTC).timestamp()): 1,
    }


def test_counts_by_day_handles_non_list() -> None:
    assert _counts_by_day({"error": "x"}) == {}


def test_is_configured_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert FinnhubNewsProvider.is_configured() is False
    monkeypatch.setenv("FINNHUB_API_KEY", "abc")
    assert FinnhubNewsProvider.is_configured() is True
