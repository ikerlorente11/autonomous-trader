"""Common-window leaderboard: arms born on different dates must be ranked on the
same sessions, or the ranking is an artefact of when each one was created."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.db.models import PortfolioNav
from backend.tests.factories import seed_portfolio

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc
DAY0 = dt.datetime(2026, 8, 3, tzinfo=UTC)  # Monday


async def _seed_nav(session, pid: int, day: int, total: float, bench: float) -> None:
    session.add(
        PortfolioNav(
            portfolio_id=pid,
            ts=DAY0 + dt.timedelta(days=day),
            cash=Decimal(str(total)),
            equity=Decimal(0),
            total=Decimal(str(total)),
            benchmark_value=Decimal(str(bench)),
        )
    )
    await session.flush()


async def test_window_is_the_intersection_and_ranking_uses_it(
    api_client, db_session
) -> None:
    # `old` has 5 sessions, `young` only the last 3 — and `old` did all its winning
    # before `young` existed. Ranked over the shared window, `young` must win.
    old = await seed_portfolio(db_session, name="lb-old", deposit=1000)
    young = await seed_portfolio(db_session, name="lb-young", deposit=1000)
    for day, total in enumerate([1000, 1200, 1200, 1200, 1200]):
        await _seed_nav(db_session, old, day, total, 1000 + day)
    for day, total in zip(range(2, 5), [1000, 1050, 1100]):
        await _seed_nav(db_session, young, day, total, 1000 + day)

    r = await api_client.get("/api/algorithms/leaderboard")
    assert r.status_code == 200
    body = r.json()

    assert body["sessions"] == 3
    assert body["start"] == "2026-08-05"
    by_name = {e["name"]: e for e in body["entries"]}
    assert by_name["lb-old"]["total_return"] == pytest.approx(0.0)
    assert by_name["lb-young"]["total_return"] == pytest.approx(0.1)
    # Ordered by excess over the benchmark, best first.
    names = [e["name"] for e in body["entries"]]
    assert names.index("lb-young") < names.index("lb-old")


async def test_portfolios_without_window_data_are_named_not_dropped(
    api_client, db_session
) -> None:
    a = await seed_portfolio(db_session, name="lb-a", deposit=1000)
    b = await seed_portfolio(db_session, name="lb-b", deposit=1000)
    absent = await seed_portfolio(db_session, name="lb-absent", deposit=1000)
    assert absent
    for day in range(3):
        await _seed_nav(db_session, a, day, 1000 + day, 1000)
        await _seed_nav(db_session, b, day, 1000 + 2 * day, 1000)

    r = await api_client.get("/api/algorithms/leaderboard")
    body = r.json()
    assert body["sessions"] == 0 or "lb-absent" in body["excluded"]


async def test_benchmark_rides_as_first_class_row(api_client, db_session) -> None:
    pid = await seed_portfolio(db_session, name="lb-vs-spy", deposit=1000)
    for day in range(3):
        await _seed_nav(db_session, pid, day, 1000, 1000 + 10 * day)

    r = await api_client.get("/api/algorithms/leaderboard")
    body = r.json()
    bench = [e for e in body["entries"] if e["is_benchmark"]]
    assert len(bench) == 1
    assert bench[0]["portfolio_id"] == 0
    assert bench[0]["total_return"] == pytest.approx(0.02)
    assert bench[0]["excess"] == pytest.approx(0.0)
    # A flat portfolio against a rising index sorts below the benchmark row.
    names = [e["name"] for e in body["entries"]]
    assert names.index(bench[0]["name"]) < names.index("lb-vs-spy")


async def test_alpha_significance_with_enough_sessions(api_client, db_session) -> None:
    # 25 sessions of +1%/day against a flat index: unambiguous positive alpha.
    pid = await seed_portfolio(db_session, name="lb-alpha", deposit=1000)
    for day in range(25):
        await _seed_nav(db_session, pid, day, 1000 * 1.01**day, 1000)

    r = await api_client.get("/api/algorithms/leaderboard")
    entry = next(e for e in r.json()["entries"] if e["name"] == "lb-alpha")
    assert entry["alpha_annual"] is not None and entry["alpha_annual"] > 0
    assert entry["alpha_ci_low"] > 0
    assert entry["alpha_p_value"] < 0.05
    assert entry["alpha_significant"] is True


async def test_alpha_gated_below_min_paired_days(api_client, db_session) -> None:
    pid = await seed_portfolio(db_session, name="lb-underpowered", deposit=1000)
    for day in range(5):
        await _seed_nav(db_session, pid, day, 1000 * 1.01**day, 1000)

    r = await api_client.get("/api/algorithms/leaderboard")
    entry = next(e for e in r.json()["entries"] if e["name"] == "lb-underpowered")
    assert entry["alpha_annual"] is None
    assert entry["alpha_p_value"] is None
    assert entry["alpha_significant"] is None


async def test_start_clips_the_window(api_client, db_session) -> None:
    pid = await seed_portfolio(db_session, name="lb-clip", deposit=1000)
    for day, total in enumerate([1000, 900, 900, 990]):
        await _seed_nav(db_session, pid, day, total, 1000)

    r = await api_client.get("/api/algorithms/leaderboard?start=2026-08-04")
    body = r.json()
    assert body["start"] == "2026-08-04"
    # Clipped: measured from the 900 trough, not from the 1000 peak before it.
    assert body["entries"][0]["total_return"] == pytest.approx(0.1)
