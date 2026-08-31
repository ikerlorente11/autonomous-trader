from __future__ import annotations

import datetime as dt
import os

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.api.schemas import (
    HealthCheckSchema,
    JobStatus,
    PipelineHealth,
    RunTrigger,
    SystemStatus,
)
from backend.db.queries.system_queries import (
    get_last_run_per_job,
    get_pipeline_freshness,
    get_recent_job_runs,
)
from backend.health import evaluate
from backend.scheduler.jobs import run_pipeline
from backend.scheduler.schedule import JOB_SCHEDULE, next_run_after

router = APIRouter(prefix="/api/system", tags=["system"])

# Single-flight guard for the manual trigger within this API process. Set
# synchronously in the handler before the background task is scheduled, so two
# rapid POSTs cannot both start a run. Cross-process overlap with the scheduler is
# already neutralized by each job's idempotency guards. The guard self-heals: if a
# run's flag is left set (e.g. a dropped background task), a later request past the
# max-runtime window treats it as stale and starts a fresh run rather than wedging.
_MAX_PIPELINE_SECONDS = 1800
_pipeline_started_at: dt.datetime | None = None


def _pipeline_in_progress(now: dt.datetime) -> bool:
    if _pipeline_started_at is None:
        return False
    return (now - _pipeline_started_at).total_seconds() < _MAX_PIPELINE_SECONDS


async def _run_pipeline_guarded() -> None:
    global _pipeline_started_at
    try:
        await run_pipeline()
    finally:
        _pipeline_started_at = None


@router.post("/run", response_model=RunTrigger)
async def run_pipeline_now(background: BackgroundTasks) -> RunTrigger:
    global _pipeline_started_at
    now = dt.datetime.now(dt.timezone.utc)
    if _pipeline_in_progress(now):
        return RunTrigger(
            status="already_running",
            detail="A pipeline run is already in progress.",
        )
    _pipeline_started_at = now
    background.add_task(_run_pipeline_guarded)
    return RunTrigger(
        status="started",
        detail="Daily pipeline started: macro, news, market data, fundamentals, "
        "analysis, trades, NAV snapshot.",
    )


@router.get("/health", response_model=PipelineHealth)
async def pipeline_health(
    session: AsyncSession = Depends(get_session),
) -> PipelineHealth:
    """Is the pipeline producing data? Polled from the host by scripts/health_alert.py.

    Always 200 — the verdict is in the body. An HTTP error code would be
    indistinguishable from the API itself being down, and the poller must be able to
    tell those apart to write a useful subject line."""
    now = dt.datetime.now(dt.timezone.utc)
    facts = await get_pipeline_freshness(
        session, failed_since=now - dt.timedelta(hours=24)
    )
    report = evaluate(
        now=now,
        latest_nav=facts.latest_nav,
        latest_bar=facts.latest_bar,
        last_job_at=facts.last_job_at,
        failed_jobs=facts.failed_jobs,
    )
    return PipelineHealth(
        ok=report.ok,
        asof=report.asof,
        checks=[
            HealthCheckSchema(name=c.name, ok=c.ok, detail=c.detail)
            for c in report.checks
        ],
    )


@router.get("/status", response_model=SystemStatus)
async def system_status(
    session: AsyncSession = Depends(get_session),
) -> SystemStatus:
    now = dt.datetime.now(dt.timezone.utc)
    last_runs = {r.job: r for r in await get_last_run_per_job(session)}
    jobs: list[JobStatus] = []
    for job in JOB_SCHEDULE:
        last = last_runs.get(job)
        jobs.append(
            JobStatus(
                job=job,
                status=last.status if last else None,
                last_run_at=last.started_at if last else None,
                ended_at=last.ended_at if last else None,
                duration_ms=last.duration_ms if last else None,
                error=last.error if last else None,
                next_run_at=next_run_after(job, now),
            )
        )
    recent = await get_recent_job_runs(session, limit=50)
    errors = [
        JobStatus(
            job=r.job,
            status=r.status,
            last_run_at=r.started_at,
            ended_at=r.ended_at,
            duration_ms=r.duration_ms,
            error=r.error,
        )
        for r in recent
        if r.status in {"failed", "degraded"}
    ]
    micro_enabled = os.environ.get("MICRO_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return SystemStatus(
        server_time=now, jobs=jobs, recent_errors=errors, micro_enabled=micro_enabled
    )
