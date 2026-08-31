import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


# Pool sized to stay within the DB's max_connections (25 on the Pi) across both the
# api and scheduler processes plus the APScheduler job store: pool_size + max_overflow
# is the per-process ceiling. asyncpg's connect timeout is raised so a cold concurrent
# burst (e.g. the dashboard's first load) doesn't fail while opening connections.
_POOL_SIZE = _int_env("DB_POOL_SIZE", 6)
_MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", 4)
# A Postgres backend never returns its private memory to the OS: catalog/plan caches
# and the peaks of big statements (bulk upserts, wide signal scans) stay resident for
# the life of the connection. With an immortal pool the scheduler's backends grew to
# 176/174/126/70 MB RSS while idle and pinned trader-db against its 512 MB cgroup —
# the OOM that froze the scheduler for 8 days on 2026-08-04. Recycling caps that
# growth: a connection older than this is closed and reopened on next checkout.
_POOL_RECYCLE = _int_env("DB_POOL_RECYCLE", 1800)

engine = create_async_engine(
    _database_url(),
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_recycle=_POOL_RECYCLE,
    pool_timeout=_int_env("DB_POOL_TIMEOUT", 30),
    connect_args={"timeout": _int_env("DB_CONNECT_TIMEOUT", 30)},
)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def warm_pool(connections: int | None = None) -> None:
    """Pre-open pooled connections concurrently so the first request burst doesn't pay
    TimescaleDB's cold connection-setup latency (which can otherwise push the
    dashboard's parallel calls past the client timeout). Best-effort: on failure the
    pool still fills lazily on demand."""
    count = connections if connections is not None else _POOL_SIZE

    async def _ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    results = await asyncio.gather(
        *(_ping() for _ in range(count)), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        logger.warning(
            "DB pool warm-up: %d/%d connections failed (%s); falling back to lazy",
            len(failures),
            count,
            failures[0],
        )
