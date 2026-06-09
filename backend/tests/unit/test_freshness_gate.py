"""P12 — data-freshness gate: exclude symbols whose latest bar is too many sessions old."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.data_ingestion.calendar import nth_prior_trading_day
from backend.scheduler.jobs import _bar_staleness_cutoff, _bars_fresh

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc


def _row(date: dt.date):
    return SimpleNamespace(ts=dt.datetime(date.year, date.month, date.day, tzinfo=UTC))


def test_nth_prior_trading_day_skips_weekends() -> None:
    # 2026-06-08 is a Monday; one session before it is Friday 2026-06-05.
    assert nth_prior_trading_day(dt.date(2026, 6, 8), 1) == dt.date(2026, 6, 5)
    # three sessions before Monday 06-08: Fri 06-05, Thu 06-04, Wed 06-03.
    assert nth_prior_trading_day(dt.date(2026, 6, 8), 3) == dt.date(2026, 6, 3)


def test_nth_prior_trading_day_disabled_for_non_positive() -> None:
    assert nth_prior_trading_day(dt.date(2026, 6, 8), 0) is None
    assert nth_prior_trading_day(dt.date(2026, 6, 8), -2) is None


def test_cutoff_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_BAR_STALENESS_DAYS", raising=False)
    assert _bar_staleness_cutoff(dt.datetime(2026, 6, 9, tzinfo=UTC)) is None


def test_cutoff_uses_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BAR_STALENESS_DAYS", "1")
    # one session before Tuesday 2026-06-09 is Monday 2026-06-08.
    assert _bar_staleness_cutoff(dt.datetime(2026, 6, 9, tzinfo=UTC)) == dt.date(2026, 6, 8)


def test_bad_env_disables_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BAR_STALENESS_DAYS", "not-a-number")
    assert _bar_staleness_cutoff(dt.datetime(2026, 6, 9, tzinfo=UTC)) is None


def test_bars_fresh_off_when_cutoff_none() -> None:
    assert _bars_fresh([_row(dt.date(2020, 1, 1))], None) is True  # gate off -> always fresh


def test_bars_fresh_accepts_recent_and_rejects_stale() -> None:
    cutoff = dt.date(2026, 6, 5)
    assert _bars_fresh([_row(dt.date(2026, 6, 4)), _row(dt.date(2026, 6, 5))], cutoff) is True
    assert _bars_fresh([_row(dt.date(2026, 6, 8))], cutoff) is True  # newer than cutoff
    assert _bars_fresh([_row(dt.date(2026, 6, 4))], cutoff) is False  # latest bar too old
    assert _bars_fresh([], cutoff) is False
