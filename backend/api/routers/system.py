from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.api.schemas import JobStatus, RunTrigger, SystemStatus
from backend.db.queries.system_queries import (
    get_last_run_per_job,
    get_recent_job_runs,
)
from backend.scheduler.jobs import run_pipeline
from backend.scheduler.schedule import JOB_SCHEDULE, next_run_after

router = APIRouter(prefix="/api/system", tags=["system"])

# Single-flight guard for the manual trigger within this API process. Set
# synchronously in the handler before the background task is scheduled, so two
# rapid POSTs cannot both start a run. Cross-process overlap with the scheduler is
# already neutralized by each job's idempotency guards.
_pipeline_running = False


async def _run_pipeline_guarded() -> None:
    global _pipeline_running
    try:
        await run_pipeline()
    finally:
        _pipeline_running = False


@router.post("/run", response_model=RunTrigger)
async def run_pipeline_now(background: BackgroundTasks) -> RunTrigger:
    global _pipeline_running
    if _pipeline_running:
        return RunTrigger(
            status="already_running",
            detail="A pipeline run is already in progress.",
        )
    _pipeline_running = True
    background.add_task(_run_pipeline_guarded)
    return RunTrigger(
        status="started",
        detail="Daily pipeline started: market data, analysis, trades, NAV snapshot.",
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
    return SystemStatus(server_time=now, jobs=jobs, recent_errors=errors)
