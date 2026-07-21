"""Shared fixtures for the backend suite.

Two layers live here:
- Pure-unit: ``strategy_config`` builds a ``StrategyConfig`` directly (no YAML/env) so
  scorer/ranker tests have deterministic, well-known thresholds and need no database.
- DB-backed (DATABASE_URL already points at the test DB — see root conftest):
  - ``db_session`` → rollback. For code that *receives* a session (queries, PaperBroker,
    PortfolioManager): bind a session to an open transaction and roll it back after.
  - ``clean_db``   → truncate. For jobs that open their *own* ``async_session()`` and
    commit; we can't roll those back, so we wipe every table afterwards.

No test may hit the real network: provider HTTP is mocked with respx (``respx_mock``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.config import (
    AtrParams,
    IndicatorParams,
    MaTrendParams,
    RankerConfig,
    RsiParams,
    ScoringConfig,
    StrategyConfig,
)
from backend.db.base import Base
from backend.db.session import engine


@pytest.fixture
def strategy_config() -> StrategyConfig:
    return StrategyConfig(
        version="test",
        ranker=RankerConfig(
            min_score_to_act=60.0,
            min_score_to_exit=45.0,
            min_data_completeness=0.5,
        ),
        scoring=ScoringConfig(
            score_min=0.0,
            score_max=100.0,
            weights={"rsi": 0.50, "ma_trend": 0.30, "atr": 0.20},
        ),
        indicators=IndicatorParams(
            ma_trend=MaTrendParams(kind="ema", period=20, sensitivity=20.0),
            rsi=RsiParams(period=14, overbought=70.0, oversold=30.0),
            atr=AtrParams(period=14, sensitivity=50.0),
        ),
    )


@pytest.fixture(scope="session")
def _test_db_ready() -> None:
    """Fail fast with guidance if the test DB isn't there. Requested only by the DB
    fixtures below, so pure-unit runs never need a database. scripts/setup-test-db.sh
    (invoked by scripts/test.sh) creates and migrates it."""
    import asyncio

    async def _check() -> bool:
        try:
            async with engine.connect() as conn:
                ok = bool(
                    await conn.scalar(sa.text("SELECT to_regclass('public.market_bars')"))
                )
        except Exception:
            ok = False
        # Drop the connection opened on this throwaway loop before it closes.
        await engine.dispose()
        return ok

    if not asyncio.run(_check()):
        pytest.exit(
            "Test DB not ready. Run `scripts/setup-test-db.sh` (or `make test`).",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def _no_ambient_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test container inherits the prod .env (scripts/test.sh --env-file), so a
    commission model activated in production would silently shift every cash/NAV
    assertion. Cost knobs are opt-in per test; the ambient values never apply."""
    monkeypatch.delenv("COMMISSION_PCT", raising=False)
    monkeypatch.delenv("COMMISSION_PER_ORDER", raising=False)


@pytest_asyncio.fixture
async def db_session(_test_db_ready: None) -> AsyncIterator[AsyncSession]:
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        # pytest-asyncio runs each test on its own loop; drop pooled connections so
        # none is reused on a later (different) loop -> "Event loop is closed".
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_db(_test_db_ready: None) -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient

    from backend.api.deps import get_session
    from backend.api.main import app

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
