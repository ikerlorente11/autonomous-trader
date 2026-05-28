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

from backend.scheduler.jobs import JOBS
from backend.scheduler.schedule import JOB_SCHEDULE

logger = logging.getLogger(__name__)

_DEFAULT_MISFIRE_GRACE = 3600


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
