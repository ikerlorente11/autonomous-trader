"""Micro universe selection — liquidity ranking against the test DB (rollback)."""

from __future__ import annotations

import datetime as dt

import pytest

from backend.analysis.micro.universe import select_micro_universe
from backend.tests import factories as f

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
# Fixed 1M volume in the factory → dollar-volume ranks by price here.
ASOF = dt.datetime(2026, 5, 10, tzinfo=UTC)
START = dt.date(2026, 5, 1)


async def _seed(session) -> None:
    await f.seed_bars(session, "BIG", closes=[300, 300, 300], start=START)
    await f.seed_bars(session, "MID", closes=[100, 100, 100], start=START)
    await f.seed_bars(session, "THIN", closes=[2, 2, 2], start=START)


async def test_ranks_by_dollar_volume_and_caps(db_session) -> None:
    await _seed(db_session)
    picked = await select_micro_universe(
        db_session, ["BIG", "MID", "THIN"], ASOF, limit=2
    )
    assert picked == ["BIG", "MID"]  # most-liquid first, capped at 2


async def test_floor_excludes_thin_names(db_session) -> None:
    await _seed(db_session)
    picked = await select_micro_universe(
        db_session,
        ["BIG", "MID", "THIN"],
        ASOF,
        limit=10,
        min_dollar_volume=50_000_000,  # MID=100M passes, THIN=2M fails
    )
    assert picked == ["BIG", "MID"]


async def test_symbols_without_history_are_excluded(db_session) -> None:
    await f.seed_bars(db_session, "BIG", closes=[300, 300], start=START)
    picked = await select_micro_universe(
        db_session, ["BIG", "NOHIST"], ASOF, limit=10
    )
    assert picked == ["BIG"]


async def test_empty_input_returns_empty(db_session) -> None:
    assert await select_micro_universe(db_session, [], ASOF, limit=5) == []
