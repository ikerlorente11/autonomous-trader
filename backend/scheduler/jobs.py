"""The four daily compute/ingestion jobs.

Two classes (workflow-tree.md §intro): ingestion jobs call external APIs and write
raw data; compute jobs read **only** from the DB and never touch the network. Every
job is idempotent, guarded by the market calendar, emits one structured-JSON line per
lifecycle event to stdout (Docker captures it), and records a ``job_runs`` row for the
dashboard health panel. Failures are recorded and swallowed so a dead source degrades
the day rather than crashing the scheduler.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator
from backend.analysis.performance.settle import settle_due_signals
from backend.analysis.scoring.persistence import (
    persist_algorithm_signals,
    persist_signal_values,
)
from backend.contracts import OHLCVBar, OrderState, RankedSymbol, SignalAction, SymbolScore
from backend.data_ingestion.calendar import is_market_open_now, is_trading_day
from backend.data_ingestion.ingest import ingest_daily_bars, upsert_bars
from backend.data_ingestion.providers.yfinance_provider import YFinanceProvider
from backend.db.models import JobRun
from backend.db.queries.market_queries import (
    count_bars_per_symbol,
    get_bars_range,
    get_latest_bars,
)
from backend.db.queries.portfolio_queries import (
    count_filled_orders_since,
    get_active_watchlist,
    get_latest_analysis_ts,
    get_open_positions,
    get_top_ranked_signals,
    list_portfolios,
)
from backend.db.session import async_session
from backend.scheduler.schedule import JOB_SCHEDULE
from backend.trading.broker_factory import make_broker
from backend.trading.portfolio_manager import PortfolioManager
from backend.trading.stops import (
    atr_stop_multiple,
    evaluate_trailing_stop,
    regime_adjustment,
    regime_enabled,
    stop_tighten_factor,
    trailing_stop_pct,
    vix_panic_above,
    vix_panic_hold,
    vix_tighten_above,
)

logger = logging.getLogger(__name__)

_ANALYSIS_LOOKBACK_DAYS = 400
# Below this many stored bars a symbol is backfilled over the full lookback window
# instead of just appending today (comfortably above the longest indicator period).
_MIN_HISTORY_BARS = 60
# The incremental fetch asks for a trailing window, not today..today: the job runs at
# 06:30 UTC — before the US session — so "today" has no settled bar yet, and a single
# day spanning a weekend/holiday would be empty. A few days back always catches the
# last close; the upsert is idempotent so re-fetching is free.
_INCREMENTAL_LOOKBACK_DAYS = 5
# Must span the whole scored universe, not just buy candidates: the manager also
# reads the low-scored end to find SELL signals on names it currently holds, so a
# larger watchlist must not truncate exits. Comfortably above the 50-symbol target.
_RANK_LIMIT = 500


def _today_utc_midnight() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _log_event(job: str, event: str, **fields: Any) -> None:
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "job": job,
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str), flush=True)


@dataclass
class JobOutcome:
    status: str = "success"
    detail: dict[str, Any] = field(default_factory=dict)


@asynccontextmanager
async def _job_context(job: str):
    run_id = _today_utc_midnight().isoformat()
    started = dt.datetime.now(dt.timezone.utc)
    t0 = time.monotonic()
    outcome = JobOutcome()
    _log_event(job, "job_start", run_id=run_id)
    error: str | None = None
    try:
        yield outcome
    except Exception as exc:  # noqa: BLE001 — record and degrade, never crash scheduler
        outcome.status = "failed"
        error = repr(exc)
        logger.exception("job %s failed", job)
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        _log_event(
            job,
            "job_complete",
            run_id=run_id,
            status=outcome.status,
            duration_ms=duration_ms,
            error=error,
            **outcome.detail,
        )
        async with async_session() as rec_session:
            rec_session.add(
                JobRun(
                    job=job,
                    run_id=run_id,
                    status=outcome.status,
                    started_at=started,
                    ended_at=dt.datetime.now(dt.timezone.utc),
                    duration_ms=duration_ms,
                    error=error,
                    detail=outcome.detail or None,
                )
            )
            await rec_session.commit()


def _bars_to_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [float(r.open) for r in rows],
            "high": [float(r.high) for r in rows],
            "low": [float(r.low) for r in rows],
            "close": [float(r.close) for r in rows],
            "volume": [int(r.volume) for r in rows],
        },
        index=[r.ts for r in rows],
    )


_ATR_PERIOD = 14
_ATR_LOOKBACK_DAYS = 40


def _latest_atr(rows) -> Decimal | None:
    """Raw ATR(14) in price units from stored daily bars, or None if too few bars."""
    if len(rows) < _ATR_PERIOD + 1:
        return None
    series = (
        AverageTrueRangeIndicator(period=_ATR_PERIOD, sensitivity=1.0)
        .compute(_bars_to_frame(rows))
        .dropna()
    )
    if series.empty:
        return None
    return Decimal(str(float(series.iloc[-1])))


# --------------------------------------------------------------------------- #
# Ingestion job (external calls)
# --------------------------------------------------------------------------- #
async def fetch_market_data() -> None:
    async with _job_context("fetch_market_data") as outcome:
        today = dt.date.today()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            _log_event("fetch_market_data", "MARKET_CLOSED", day=today.isoformat())
            return
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            symbols = [w.symbol for w in watchlist]
            if not symbols:
                outcome.status = "skipped"
                outcome.detail = {"reason": "empty_watchlist"}
                return
            asof = _today_utc_midnight()
            lookback_start = today - dt.timedelta(days=_ANALYSIS_LOOKBACK_DAYS)
            counts = await count_bars_per_symbol(
                session, symbols, asof - dt.timedelta(days=_ANALYSIS_LOOKBACK_DAYS), asof
            )
            backfill = [s for s in symbols if counts.get(s, 0) < _MIN_HISTORY_BARS]
            current = [s for s in symbols if counts.get(s, 0) >= _MIN_HISTORY_BARS]
            reports = []
            if backfill:
                reports.append(
                    await ingest_daily_bars(session, backfill, lookback_start, today)
                )
            if current:
                incremental_start = today - dt.timedelta(days=_INCREMENTAL_LOOKBACK_DAYS)
                reports.append(
                    await ingest_daily_bars(session, current, incremental_start, today)
                )
            missing = [s for r in reports for s in r.empty_symbols]
            outcome.status = "degraded" if missing else "success"
            outcome.detail = {
                "symbols_requested": len(symbols),
                "symbols_backfilled": len(backfill),
                "symbols_missing": missing,
                "anomalies": sum(len(r.anomalies) for r in reports),
            }


# --------------------------------------------------------------------------- #
# Compute jobs (DB-only, no network)
# --------------------------------------------------------------------------- #
async def run_analysis() -> None:
    async with _job_context("run_analysis") as outcome:
        today = dt.date.today()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
        asof = _today_utc_midnight()
        start = asof - dt.timedelta(days=_ANALYSIS_LOOKBACK_DAYS)
        engine = DefaultAnalysisEngine()
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            indicators = []
            scores = []
            for entry in watchlist:
                rows = await get_bars_range(session, entry.symbol, start, asof)
                if not rows:
                    continue
                frame = _bars_to_frame(rows)
                indicators.extend(
                    engine.compute_indicators({entry.symbol: frame}, asof)
                )
                scores.append(engine.score_symbol(entry.symbol, frame, asof))
            if not scores:
                outcome.status = "degraded"
                outcome.detail = {"reason": "NO_SIGNALS", "symbols_scored": 0}
                _log_event("run_analysis", "NO_SIGNALS")
                return
            await persist_signal_values(session, indicators)
            await persist_algorithm_signals(session, scores, engine.strategy_version)
            settled = await settle_due_signals(session, asof)
            await session.commit()
            outcome.detail = {
                "symbols_scored": len(scores),
                "strategy_version": engine.strategy_version,
                "signals_settled": settled,
            }


async def execute_paper_trades() -> None:
    async with _job_context("execute_paper_trades") as outcome:
        today = dt.date.today()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
        async with async_session() as session:
            asof = await get_latest_analysis_ts(session)
            if asof is None:
                outcome.status = "skipped"
                outcome.detail = {"reason": "NO_SIGNALS"}
                return
            portfolios = await list_portfolios(session, active_only=True)
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_active_portfolios"}
                return
            signals = await get_top_ranked_signals(session, asof, limit=_RANK_LIMIT)
            ranked = [
                RankedSymbol(
                    rank=i + 1,
                    score=SymbolScore(
                        symbol=s.symbol,
                        ts=s.ts,
                        score=s.score,
                        action=SignalAction(s.action),
                        reason=s.reason,
                        indicator_snapshot=s.indicator_snapshot,
                        data_completeness=s.data_completeness,
                    ),
                )
                for i, s in enumerate(signals)
            ]
            engine = DefaultAnalysisEngine()
            midnight = _today_utc_midnight()
            total_orders = 0
            per_portfolio: dict[str, int] = {}
            skipped: list[int] = []
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                # Per-portfolio idempotency: don't double-trade one already traded today.
                if await count_filled_orders_since(session, portfolio.id, midnight) > 0:
                    skipped.append(portfolio.id)
                    continue
                # Each portfolio runs in its own savepoint so one failure rolls back only
                # that portfolio, never the fills already booked for the others (H3).
                try:
                    async with session.begin_nested():
                        broker = make_broker(
                            session, portfolio.id,
                            strategy_version=engine.strategy_version,
                        )
                        manager = PortfolioManager(broker, session, portfolio.id)
                        orders = await manager.execute_signals(ranked)
                    per_portfolio[str(portfolio.id)] = len(orders)
                    total_orders += len(orders)
                except Exception as exc:  # noqa: BLE001 — isolate, record, continue
                    failed[str(portfolio.id)] = repr(exc)
                    logger.exception("execute_paper_trades failed for portfolio %s", portfolio.id)
            await session.commit()
            if failed:
                outcome.status = "degraded"
            outcome.detail = {
                "orders": total_orders,
                "per_portfolio": per_portfolio,
                "skipped_already_traded": skipped,
                "failed": failed,
            }


async def update_portfolio_nav() -> None:
    async with _job_context("update_portfolio_nav") as outcome:
        async with async_session() as session:
            portfolios = await list_portfolios(session, active_only=True)
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_active_portfolios"}
                return
            navs: dict[str, str] = {}
            stale_marks: dict[str, list[str]] = {}
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                try:
                    async with session.begin_nested():
                        broker = make_broker(session, portfolio.id)
                        manager = PortfolioManager(broker, session, portfolio.id)
                        _, stale = await manager.update_positions()
                        snapshot = await manager.snapshot_nav()
                    navs[str(portfolio.id)] = str(snapshot.total)
                    if stale:
                        stale_marks[str(portfolio.id)] = stale
                except Exception as exc:  # noqa: BLE001 — isolate, record, continue
                    failed[str(portfolio.id)] = repr(exc)
                    logger.exception("update_portfolio_nav failed for portfolio %s", portfolio.id)
            await session.commit()
            if failed:
                outcome.status = "degraded"
            outcome.detail = {
                "nav_total_by_portfolio": navs,
                "stale_marks": stale_marks,
                "failed": failed,
            }


_PROTECTIVE_SELL_STRATEGY = "protective-sell"


def _protective_sell_enabled() -> bool:
    return os.environ.get("PROTECTIVE_SELL_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


async def protective_sell() -> None:
    """Intraday trailing-stop guard (interval job, market hours only).

    For every held position it ratchets a high-water mark on the live price and, when
    the price has retraced past the trailing stop from that peak, sells the position in
    full — cutting losses and locking in gains without waiting for the daily pipeline.
    Sells are tagged ``strategy_version='protective-sell'`` so they're distinguishable in
    the trades table. The broker fills against the latest stored bar, so the live price is
    first marked as today's bar (overwritten by the next morning's fetch)."""
    async with _job_context("protective_sell") as outcome:
        if not _protective_sell_enabled():
            outcome.status = "skipped"
            outcome.detail = {"reason": "DISABLED"}
            return
        if not is_market_open_now():
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return

        pct = trailing_stop_pct()
        atr_mult = atr_stop_multiple()
        provider = YFinanceProvider()
        asof = _today_utc_midnight()

        # Market-stress regime from a live VIX read (best-effort): tighten the stop under
        # stress, but hold (don't sell) in outright panic — extreme VIX is often the bottom.
        distance_factor = Decimal(1)
        panic_hold = False
        vix_val: Decimal | None = None
        if regime_enabled():
            vix_val = (await provider.fetch_live_prices(["^VIX"])).get("^VIX")
            distance_factor, panic_hold = regime_adjustment(
                vix_val,
                tighten_above=vix_tighten_above(),
                panic_above=vix_panic_above(),
                tighten_factor=stop_tighten_factor(),
            )
            if panic_hold and not vix_panic_hold():
                panic_hold = False  # operator opted to always protect

        async with async_session() as session:
            portfolios = await list_portfolios(session, active_only=True)
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_active_portfolios"}
                return

            atr_start = asof - dt.timedelta(days=_ATR_LOOKBACK_DAYS)
            triggered_total = 0
            per_portfolio: dict[str, int] = {}
            for portfolio in portfolios:
                positions = await get_open_positions(session, portfolio.id)
                if not positions:
                    continue
                symbols = [p.symbol for p in positions]
                live = await provider.fetch_live_prices(symbols)
                # Feed fallback: if the live quote is missing (Yahoo 429), fall back to the
                # latest stored close so the stop still evaluates rather than going blind.
                missing = [s for s in symbols if s not in live]
                if missing:
                    for b in await get_latest_bars(session, missing):
                        live.setdefault(b.symbol, b.close)
                broker = make_broker(
                    session, portfolio.id, strategy_version=_PROTECTIVE_SELL_STRATEGY
                )
                triggered = 0
                for position in positions:
                    price = live.get(position.symbol)
                    if price is None:
                        continue
                    atr = _latest_atr(
                        await get_bars_range(session, position.symbol, atr_start, asof)
                    )
                    new_hwm, hit = evaluate_trailing_stop(
                        position.avg_cost, position.high_water_mark, price,
                        pct=pct, atr=atr, atr_multiple=atr_mult,
                        distance_factor=distance_factor,
                    )
                    position.high_water_mark = new_hwm  # ratchet up, persisted on commit
                    if not hit or panic_hold:
                        continue
                    # Mark today's bar at the live price so the simulated fill is realistic.
                    await upsert_bars(
                        session,
                        [OHLCVBar(
                            symbol=position.symbol, ts=asof, open=price, high=price,
                            low=price, close=price, volume=0, adj_close=price,
                        )],
                    )
                    order = await broker.place_order(
                        position.symbol, "sell", position.qty, "market"
                    )
                    if order.status is OrderState.FILLED:
                        triggered += 1
                        _log_event(
                            "protective_sell", "stop_triggered",
                            portfolio_id=portfolio.id, symbol=position.symbol,
                            avg_cost=str(position.avg_cost), peak=str(new_hwm),
                            live_price=str(price), atr=str(atr) if atr is not None else None,
                        )
                per_portfolio[str(portfolio.id)] = triggered
                triggered_total += triggered

            await session.commit()
            outcome.detail = {
                "stops_triggered": triggered_total,
                "trailing_stop_pct": str(pct),
                "atr_multiple": str(atr_mult),
                "vix": str(vix_val) if vix_val is not None else None,
                "panic_hold": panic_hold,
                "per_portfolio": per_portfolio,
            }


JOBS: dict[str, Callable[[], Awaitable[None]]] = {
    "fetch_market_data": fetch_market_data,
    "run_analysis": run_analysis,
    "execute_paper_trades": execute_paper_trades,
    "update_portfolio_nav": update_portfolio_nav,
    "protective_sell": protective_sell,
}


async def run_pipeline() -> list[str]:
    """Run the daily jobs in canonical order, on demand (manual trigger).

    Each job owns its session, records a ``job_runs`` row and swallows its own
    errors, so one failing step degrades the run rather than aborting the rest —
    the same guarantee the scheduler relies on. Idempotency guards make a manual
    run safe even if the scheduler already ran today.
    """
    completed: list[str] = []
    for job_name in JOB_SCHEDULE:
        await JOBS[job_name]()
        completed.append(job_name)
    return completed
