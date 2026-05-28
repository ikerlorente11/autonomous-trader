"""Canonical daily job schedule (UTC), shared by the scheduler and the API.

A plain config constant — no logic — so the API can derive each job's next run
time without coupling to the scheduler process (services share only the DB; this
is a build-time constant, not a runtime call). Times are the CLAUDE.md sequence.
"""

from __future__ import annotations

import datetime as dt

JOB_SCHEDULE: dict[str, tuple[int, int]] = {
    "fetch_market_data": (6, 30),
    "run_analysis": (7, 30),
    "execute_paper_trades": (8, 0),
    "update_portfolio_nav": (8, 15),
}


def next_run_after(job: str, now: dt.datetime) -> dt.datetime | None:
    """The next UTC datetime ``job`` is scheduled to run at or after ``now``."""
    slot = JOB_SCHEDULE.get(job)
    if slot is None:
        return None
    hour, minute = slot
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < now:
        candidate += dt.timedelta(days=1)
    return candidate
