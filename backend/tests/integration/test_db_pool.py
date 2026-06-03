"""DB pool warm-up — opens connections and leaves the engine usable."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.db.session import engine, warm_pool

pytestmark = pytest.mark.integration


async def test_warm_pool_runs_and_engine_usable() -> None:
    try:
        await warm_pool(3)  # idempotent, best-effort
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    finally:
        # pytest-asyncio runs each test on its own loop; drop the connections this
        # test opened so none is reused on a later loop (mirrors the db_session /
        # clean_db fixtures). Without this the pooled conns leak and break later setup.
        await engine.dispose()
