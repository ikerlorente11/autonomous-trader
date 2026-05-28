from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import JobRun


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
