"""Pipeline liveness verdicts — the alarm that the 2026-08-04 blackout lacked."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.health import evaluate, sessions_behind

pytestmark = pytest.mark.unit

UTC = dt.timezone.utc
# 2026-08-31 is a Monday; the prior sessions are Fri 08-28, Thu 08-27, Wed 08-26.
NOW = dt.datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


def _healthy(**overrides):
    facts = {
        "now": NOW,
        "latest_nav": dt.date(2026, 8, 28),
        "latest_bar": dt.date(2026, 8, 28),
        "last_job_at": NOW - dt.timedelta(minutes=10),
        "failed_jobs": 0,
    }
    facts.update(overrides)
    return evaluate(**facts)


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_sessions_behind_counts_trading_days_only() -> None:
    # Friday -> Monday is one session, not three days.
    assert sessions_behind(dt.date(2026, 8, 28), dt.date(2026, 8, 31)) == 1
    assert sessions_behind(dt.date(2026, 8, 31), dt.date(2026, 8, 31)) == 0
    assert sessions_behind(None, dt.date(2026, 8, 31)) is None


def test_a_working_pipeline_is_healthy() -> None:
    assert _healthy().ok is True


def test_frozen_scheduler_is_caught_by_silence() -> None:
    # The exact 2026-08-04 shape: the process is up, nothing failed, nothing runs.
    report = _healthy(last_job_at=NOW - dt.timedelta(hours=30))
    assert report.ok is False
    assert _check(report, "scheduler_alive").ok is False


def test_stale_nav_is_caught_even_if_jobs_look_alive() -> None:
    report = _healthy(latest_nav=dt.date(2026, 8, 20))
    assert report.ok is False
    assert _check(report, "nav_fresh").ok is False


def test_stale_bars_are_caught() -> None:
    report = _healthy(latest_bar=dt.date(2026, 8, 18))
    assert report.ok is False
    assert _check(report, "bars_fresh").ok is False


def test_failed_jobs_flip_the_verdict() -> None:
    report = _healthy(failed_jobs=2)
    assert report.ok is False
    assert _check(report, "no_failed_jobs").ok is False


def test_empty_database_is_unhealthy_not_crashy() -> None:
    report = evaluate(
        now=NOW, latest_nav=None, latest_bar=None, last_job_at=None, failed_jobs=0
    )
    assert report.ok is False
    assert [c.ok for c in report.checks].count(False) == 3


def test_thresholds_are_env_tunable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_MAX_JOB_SILENCE_HOURS", "48")
    assert _healthy(last_job_at=NOW - dt.timedelta(hours=30)).ok is True


def test_bad_threshold_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_MAX_JOB_SILENCE_HOURS", "not-a-number")
    assert _healthy(last_job_at=NOW - dt.timedelta(hours=30)).ok is False
