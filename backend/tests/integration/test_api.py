"""API endpoints via httpx ASGITransport — session overridden to the test DB."""

from __future__ import annotations

import pytest

from backend.db.queries.portfolio_queries import upsert_watchlist_symbol

pytestmark = pytest.mark.integration


async def test_health_ok(api_client) -> None:
    r = await api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_system_status_lists_all_jobs(api_client) -> None:
    r = await api_client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    jobs = {j["job"] for j in body["jobs"]}
    assert jobs == {
        "fetch_macro_data",
        "fetch_news_sentiment",
        "fetch_market_data",
        "fetch_fundamentals",
        "run_analysis",
        "execute_paper_trades",
        "update_portfolio_nav",
    }


async def test_watchlist_returns_seeded_symbol(api_client, db_session) -> None:
    await upsert_watchlist_symbol(db_session, "AAPL")  # same session the API reads
    r = await api_client.get("/api/market/watchlist")
    assert r.status_code == 200
    assert "AAPL" in [e["symbol"] for e in r.json()]
