"""FP&A period & attribution endpoints over the test DB.

Assertions use the ``inception`` period and NAV rows dated well in the past so they
hold regardless of the wall-clock run date (WTD/MTD/YTD boundaries move; inception
and "all NAV predates the current period" do not)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.db.models import PortfolioNav
from backend.db.queries.portfolio_queries import upsert_watchlist_symbol
from backend.tests.factories import seed_latest_bar, seed_portfolio, seed_position

pytestmark = pytest.mark.integration

UTC = dt.timezone.utc


async def _seed_nav(session, portfolio_id: int, ts: dt.datetime, total: float) -> None:
    session.add(
        PortfolioNav(
            portfolio_id=portfolio_id,
            ts=ts,
            cash=Decimal(str(total)),
            equity=Decimal(0),
            total=Decimal(str(total)),
        )
    )
    await session.flush()


async def test_performance_periods_returns_four_tiles(api_client, db_session) -> None:
    pid = await seed_portfolio(db_session, name="P")
    await _seed_nav(db_session, pid, dt.datetime(2020, 1, 1, tzinfo=UTC), 10_000.0)
    await _seed_nav(db_session, pid, dt.datetime(2020, 2, 1, tzinfo=UTC), 10_500.0)

    r = await api_client.get(f"/api/portfolio/performance/periods?portfolio_id={pid}")
    assert r.status_code == 200
    body = {p["period"]: p for p in r.json()}
    assert set(body) == {"wtd", "mtd", "ytd", "inception"}

    assert body["inception"]["pnl"] == pytest.approx(500.0)
    assert body["inception"]["return_pct"] == pytest.approx(0.05)
    assert body["inception"]["end_value"] == pytest.approx(10_500.0)
    # Both NAV rows predate the current week/month/year -> baseline is the latest
    # past close, so the running period shows no change.
    assert body["mtd"]["pnl"] == pytest.approx(0.0)


async def test_attribution_by_symbol_and_sector(api_client, db_session) -> None:
    pid = await seed_portfolio(db_session, name="P")
    await upsert_watchlist_symbol(db_session, "AAPL", sector="Tech")
    await seed_position(db_session, pid, "AAPL", qty=10, avg_cost=100.0)
    await seed_latest_bar(db_session, "AAPL", close=110.0)  # unrealized = +100

    by_symbol = await api_client.get(
        f"/api/portfolio/attribution?portfolio_id={pid}&period=inception&by=symbol"
    )
    assert by_symbol.status_code == 200
    sbody = by_symbol.json()
    assert sbody["axis"] == "symbol"
    assert sbody["total_pnl"] == pytest.approx(100.0)
    aapl = next(s for s in sbody["symbols"] if s["symbol"] == "AAPL")
    assert aapl["unrealized_pnl"] == pytest.approx(100.0)
    assert aapl["realized_pnl"] == pytest.approx(0.0)
    assert aapl["contribution_pct"] == pytest.approx(100.0)

    by_sector = await api_client.get(
        f"/api/portfolio/attribution?portfolio_id={pid}&period=inception&by=sector"
    )
    assert by_sector.status_code == 200
    secbody = by_sector.json()
    assert secbody["axis"] == "sector"
    tech = next(s for s in secbody["sectors"] if s["sector"] == "Tech")
    assert tech["total_pnl"] == pytest.approx(100.0)
