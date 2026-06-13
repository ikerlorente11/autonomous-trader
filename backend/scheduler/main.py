"""Scheduler entrypoint — APScheduler with a PostgreSQL job store.

The job store is load-bearing for reboot recovery (workflow-tree.md §5): the
schedule survives a Pi reboot and missed runs are evaluated against
``misfire_grace_time`` with ``coalesce`` collapsing storms. Job times are the
canonical UTC schedule (``schedule.JOB_SCHEDULE``). Jobs are async coroutines run
on the AsyncIO event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.scheduler.jobs import JOBS
from backend.scheduler.schedule import JOB_SCHEDULE

logger = logging.getLogger(__name__)

_DEFAULT_MISFIRE_GRACE = 3600
_DEFAULT_PROTECTIVE_SELL_INTERVAL_MIN = 15
_DEFAULT_MICRO_INTRADAY_INTERVAL_MIN = 5
_DEFAULT_MICRO_RUN_INTERVAL_MIN = 15
_DEFAULT_MICRO_EOD_FLATTEN_CHECK_MIN = 5
_TRUTHY = {"1", "true", "yes", "on"}


def _protective_sell_enabled() -> bool:
    return os.environ.get("PROTECTIVE_SELL_ENABLED", "true").strip().lower() in _TRUTHY


def _protective_sell_interval_min() -> int:
    raw = os.environ.get("PROTECTIVE_SELL_INTERVAL_MIN")
    if raw is None or raw.strip() == "":
        return _DEFAULT_PROTECTIVE_SELL_INTERVAL_MIN
    return int(raw)


def _micro_enabled() -> bool:
    # Off by default: the microtrading section is opt-in and must not poll providers
    # (or touch the Pi budget) until the owner enables it.
    return os.environ.get("MICRO_ENABLED", "false").strip().lower() in _TRUTHY


def _micro_intraday_interval_min() -> int:
    raw = os.environ.get("MICRO_INTRADAY_INTERVAL_MIN")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MICRO_INTRADAY_INTERVAL_MIN
    return int(raw)


def _micro_run_interval_min() -> int:
    raw = os.environ.get("MICRO_RUN_INTERVAL_MIN")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MICRO_RUN_INTERVAL_MIN
    return int(raw)


def _micro_eod_flatten_check_min() -> int:
    raw = os.environ.get("MICRO_EOD_FLATTEN_CHECK_MIN")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MICRO_EOD_FLATTEN_CHECK_MIN
    return int(raw)


def _jobstore_url() -> str:
    override = os.environ.get("SCHEDULER_DB_URL")
    if override:
        return override
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL (or SCHEDULER_DB_URL) must be set")
    return url.replace("+asyncpg", "+psycopg")


def _misfire_grace_time() -> int:
    raw = os.environ.get("MISFIRE_GRACE_TIME")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MISFIRE_GRACE
    return int(raw)


def build_scheduler() -> AsyncIOScheduler:
    timezone = os.environ.get("SCHEDULER_TIMEZONE", "UTC")
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=_jobstore_url())},
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": _misfire_grace_time(),
        },
        timezone=timezone,
    )
    for job_name, (hour, minute) in JOB_SCHEDULE.items():
        scheduler.add_job(
            JOBS[job_name],
            trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
            id=job_name,
            replace_existing=True,
        )
    # Intraday trailing-stop guard — an interval job, not part of the daily JOB_SCHEDULE
    # (which the API shares to derive next-run times). The job itself no-ops outside
    # market hours; coalesce/max_instances=1 (job_defaults) prevent overlap.
    if _protective_sell_enabled():
        scheduler.add_job(
            JOBS["protective_sell"],
            trigger=IntervalTrigger(minutes=_protective_sell_interval_min()),
            id="protective_sell",
            replace_existing=True,
        )
    # Microtrading interval jobs — market-hours-gated, opt-in (MICRO_ENABLED). The jobs
    # self-gate (data poll & run_micro no-op outside market hours; eod_flatten only acts
    # near the close), so coalesce/max_instances=1 prevent overlap.
    if _micro_enabled():
        scheduler.add_job(
            JOBS["fetch_intraday_bars"],
            trigger=IntervalTrigger(minutes=_micro_intraday_interval_min()),
            id="fetch_intraday_bars",
            replace_existing=True,
        )
        scheduler.add_job(
            JOBS["run_micro"],
            trigger=IntervalTrigger(minutes=_micro_run_interval_min()),
            id="run_micro",
            replace_existing=True,
        )
        scheduler.add_job(
            JOBS["micro_eod_flatten"],
            trigger=IntervalTrigger(minutes=_micro_eod_flatten_check_min()),
            id="micro_eod_flatten",
            replace_existing=True,
        )
    return scheduler


async def _run() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(message)s",
    )
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("scheduler started with jobs: %s", ", ".join(JOB_SCHEDULE))
    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        scheduler.shutdown()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
