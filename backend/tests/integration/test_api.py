"""API endpoints via httpx ASGITransport — session overridden to the test DB."""

from __future__ import annotations

import pytest

from backend.db.queries.portfolio_queries import upsert_watchlist_symbol
from backend.tests import factories as f

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
        "settle_pending_orders",
        "run_analysis",
        "execute_paper_trades",
        "update_portfolio_nav",
    }


async def test_system_status_exposes_micro_enabled(api_client) -> None:
    r = await api_client.get("/api/system/status")
    assert r.status_code == 200
    assert "micro_enabled" in r.json()  # the /micro section reads this


async def test_portfolio_list_exposes_kind(api_client, db_session) -> None:
    # The split daily/micro switcher filters on `kind`, so the API must return it.
    await f.seed_portfolio(db_session, name="kind-check", deposit=500)
    r = await api_client.get("/api/portfolios")
    assert r.status_code == 200
    rows = r.json()
    assert rows and all("kind" in p for p in rows)
    assert any(p["kind"] == "daily" for p in rows)


async def test_watchlist_returns_seeded_symbol(api_client, db_session) -> None:
    await upsert_watchlist_symbol(db_session, "AAPL")  # same session the API reads
    r = await api_client.get("/api/market/watchlist")
    assert r.status_code == 200
    assert "AAPL" in [e["symbol"] for e in r.json()]


async def test_strategies_lists_available_versions(api_client) -> None:
    r = await api_client.get("/api/strategies")
    assert r.status_code == 200
    labels = {v["label"] for v in r.json()}
    assert {"v1", "v2"} <= labels


async def test_patch_sets_portfolio_strategy_label(api_client, db_session) -> None:
    pid = await f.seed_portfolio(db_session, name="ab-v2", deposit=500)
    r = await api_client.patch(f"/api/portfolios/{pid}", json={"strategy_label": "v2"})
    assert r.status_code == 200
    assert r.json()["strategy_label"] == "v2"


async def test_patch_rejects_unknown_strategy_version(api_client, db_session) -> None:
    pid = await f.seed_portfolio(db_session, name="ab-bogus", deposit=500)
    r = await api_client.patch(f"/api/portfolios/{pid}", json={"strategy_label": "bogus"})
    assert r.status_code == 400


async def test_patch_retires_and_revives_portfolio(api_client, db_session) -> None:
    # Retiring a losing version must stop it trading WITHOUT deleting its history.
    pid = await f.seed_portfolio(db_session, name="ab-retire", deposit=500)
    r = await api_client.patch(f"/api/portfolios/{pid}", json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False
    r = await api_client.patch(f"/api/portfolios/{pid}", json={"active": True})
    assert r.json()["active"] is True


async def test_patch_rename_still_works(api_client, db_session) -> None:
    pid = await f.seed_portfolio(db_session, name="ab-old", deposit=500)
    r = await api_client.patch(f"/api/portfolios/{pid}", json={"name": "ab-new"})
    assert r.status_code == 200
    assert r.json()["name"] == "ab-new"


async def test_portfolio_costs_attribution(api_client, db_session, monkeypatch) -> None:
    # One buy + one sell with commissions on: the endpoint must split friction out.
    monkeypatch.setenv("SLIPPAGE_PCT", "0")
    monkeypatch.setenv("COMMISSION_PCT", "0.001")
    from decimal import Decimal as D

    from backend.trading.paper_broker import PaperBroker

    pid = await f.seed_portfolio(db_session, name="costs-check", deposit=10_000)
    await f.seed_latest_bar(db_session, "AAPL", close=100)
    broker = PaperBroker(db_session, pid)
    await broker.place_order("AAPL", "buy", D("10"), "market")
    await broker.place_order("AAPL", "sell", D("10"), "market")
    await db_session.commit()

    r = await api_client.get(f"/api/portfolios/{pid}/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["fills"] == 2 and body["buys"] == 1 and body["sells"] == 1
    assert float(body["buy_notional"]) == 1000.0
    assert float(body["commission_total"]) == 2.0  # 0.1% x 1000 x 2 sides
    assert float(body["realized_flow"]) == 0.0

    r404 = await api_client.get("/api/portfolios/999999/costs")
    assert r404.status_code == 404
