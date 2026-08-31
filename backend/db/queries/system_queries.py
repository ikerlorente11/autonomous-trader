from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import JobRun, MarketBar, PortfolioNav


async def get_last_run_per_job(session: AsyncSession) -> Sequence[JobRun]:
    """The most recent run record for each distinct job (system-health panel)."""
    stmt: Select[tuple[JobRun]] = (
        select(JobRun)
        .distinct(JobRun.job)
        .order_by(JobRun.job, JobRun.started_at.desc())
    )
    return (await session.scalars(stmt)).all()


async def get_recent_job_runs(
    session: AsyncSession, limit: int = 50
) -> Sequence[JobRun]:
    """Most recent job runs across all jobs (health timeline / error feed)."""
    stmt: Select[tuple[JobRun]] = (
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    )
    return (await session.scalars(stmt)).all()


@dataclass(frozen=True)
class PipelineFreshness:
    """Raw liveness facts, straight from the DB. Verdicts live in backend.health."""

    latest_nav: dt.date | None
    latest_bar: dt.date | None
    last_job_at: dt.datetime | None
    failed_jobs: int


async def get_pipeline_freshness(
    session: AsyncSession, *, failed_since: dt.datetime
) -> PipelineFreshness:
    """What the alerting needs in one round trip.

    Deliberately not derived from job status: a frozen scheduler writes no failure
    row at all (2026-08-04), so liveness must be read from the data it should have
    produced, not from what it said about itself."""
    latest_nav = (await session.execute(select(func.max(PortfolioNav.ts)))).scalar()
    latest_bar = (await session.execute(select(func.max(MarketBar.ts)))).scalar()
    last_job_at = (await session.execute(select(func.max(JobRun.started_at)))).scalar()
    failed = (
        await session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.status == "failed", JobRun.started_at >= failed_since)
        )
    ).scalar() or 0
    return PipelineFreshness(
        latest_nav=latest_nav.date() if latest_nav else None,
        latest_bar=latest_bar.date() if latest_bar else None,
        last_job_at=last_job_at,
        failed_jobs=int(failed),
    )
