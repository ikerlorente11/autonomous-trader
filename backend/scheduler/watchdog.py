"""Scheduler watchdog — exit the process when APScheduler silently stalls.

Incident 2026-08-04: the kernel OOM-killed a Postgres backend; the postmaster
restarted every connection and APScheduler's scheduler thread died on the broken
job-store commit — while the PROCESS stayed alive. Docker saw the container "Up",
the deploy fallback had nothing to deploy, and the system sat blind for 8 days
(no data, no protective stops, no NAV).

The cure is structural: a 5-minute heartbeat job (memory job store, so it needs
no DB and no persistence) refreshes a monotonic timestamp; a plain daemon thread
— independent of the possibly-hung asyncio loop — checks it once a minute and
``os._exit``s when the gap exceeds the stall threshold. The container's
``restart: unless-stopped`` policy then revives a fresh scheduler. Exiting is
always safe: jobs are idempotent and the schedule lives in the DB job store.
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_DEFAULT_STALL_SECONDS = 1800  # heartbeat fires every 5 min; 30 min = 6 missed beats
_last_beat = time.monotonic()


def stall_seconds() -> int:
    raw = os.environ.get("SCHEDULER_WATCHDOG_STALL_SECONDS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_STALL_SECONDS
    return int(raw)


def beat() -> None:
    global _last_beat
    _last_beat = time.monotonic()


def gap_seconds() -> float:
    return time.monotonic() - _last_beat


async def heartbeat_job() -> None:
    """Scheduled every 5 minutes on the in-memory job store: its only purpose is
    proving the scheduler still executes jobs."""
    beat()


def start(threshold: int | None = None) -> threading.Thread:
    limit = threshold if threshold is not None else stall_seconds()

    def _watch() -> None:
        while True:
            time.sleep(60)
            gap = gap_seconds()
            if gap > limit:
                logger.critical(
                    "scheduler stalled: no heartbeat for %.0fs (limit %ds) — "
                    "exiting so the container restart policy revives a fresh scheduler",
                    gap,
                    limit,
                )
                os._exit(75)

    thread = threading.Thread(target=_watch, daemon=True, name="scheduler-watchdog")
    thread.start()
    return thread
