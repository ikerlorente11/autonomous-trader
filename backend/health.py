"""Pipeline liveness verdicts — is the system actually working?

Born from the 2026-08-04 blackout: APScheduler's thread died while the process
stayed alive, so nothing failed, nothing restarted, and nobody noticed for 8 days.
The lesson is that health cannot be read from a component's own report — it has to
be read from the *data the system should have produced by now*.

Pure functions over facts (see ``system_queries.get_pipeline_freshness``); the API
exposes them and ``scripts/health_alert.py`` turns a red verdict into an email from
outside Docker, so a frozen scheduler cannot silence its own alarm.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

from backend.data_ingestion.calendar import trading_days

# Every 15 minutes an interval job records a row (even a skipped one), so two hours
# of silence means the scheduler thread is gone, not that the market is closed.
_DEFAULT_MAX_JOB_SILENCE_HOURS = 2
# NAV is stamped for the running day at 08:15 UTC; bars carry the previous close.
# One extra session of slack each absorbs a late run without crying wolf.
_DEFAULT_MAX_NAV_AGE_SESSIONS = 1
_DEFAULT_MAX_BAR_AGE_SESSIONS = 2


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    checks: list[Check]
    asof: dt.datetime


def sessions_behind(day: dt.date | None, today: dt.date) -> int | None:
    """Trading sessions between ``day`` and ``today`` (0 = today's session).

    None when there is no data at all — a distinct condition from being stale, and
    the one a brand-new or freshly reset database is in."""
    if day is None:
        return None
    if day >= today:
        return 0
    return max(0, len(trading_days(day, today)) - 1)


def evaluate(
    *,
    now: dt.datetime,
    latest_nav: dt.date | None,
    latest_bar: dt.date | None,
    last_job_at: dt.datetime | None,
    failed_jobs: int,
) -> HealthReport:
    """Turn liveness facts into pass/fail checks. Thresholds are env-tunable."""
    today = now.date()
    checks: list[Check] = []

    silence_limit = _int_env("HEALTH_MAX_JOB_SILENCE_HOURS", _DEFAULT_MAX_JOB_SILENCE_HOURS)
    if last_job_at is None:
        checks.append(Check("scheduler_alive", False, "no job has ever run"))
    else:
        hours = (now - last_job_at).total_seconds() / 3600
        checks.append(
            Check(
                "scheduler_alive",
                hours <= silence_limit,
                f"last job {hours:.1f}h ago (limit {silence_limit}h)",
            )
        )

    nav_age = sessions_behind(latest_nav, today)
    nav_limit = _int_env("HEALTH_MAX_NAV_AGE_SESSIONS", _DEFAULT_MAX_NAV_AGE_SESSIONS)
    if nav_age is None:
        checks.append(Check("nav_fresh", False, "no NAV snapshot at all"))
    else:
        checks.append(
            Check(
                "nav_fresh",
                nav_age <= nav_limit,
                f"latest NAV {latest_nav} — {nav_age} sessions behind (limit {nav_limit})",
            )
        )

    bar_age = sessions_behind(latest_bar, today)
    bar_limit = _int_env("HEALTH_MAX_BAR_AGE_SESSIONS", _DEFAULT_MAX_BAR_AGE_SESSIONS)
    if bar_age is None:
        checks.append(Check("bars_fresh", False, "no market bars at all"))
    else:
        checks.append(
            Check(
                "bars_fresh",
                bar_age <= bar_limit,
                f"latest bar {latest_bar} — {bar_age} sessions behind (limit {bar_limit})",
            )
        )

    checks.append(
        Check(
            "no_failed_jobs",
            failed_jobs == 0,
            f"{failed_jobs} failed job runs in the last 24h",
        )
    )

    return HealthReport(ok=all(c.ok for c in checks), checks=checks, asof=now)
