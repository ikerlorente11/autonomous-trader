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
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.scoring.persistence import (
    persist_algorithm_signals,
    persist_signal_values,
)
from backend.contracts import RankedSymbol, SignalAction, SymbolScore
from backend.data_ingestion.calendar import is_trading_day
from backend.data_ingestion.ingest import ingest_daily_bars
from backend.db.models import JobRun
from backend.db.queries.market_queries import count_bars_per_symbol, get_bars_range
from backend.db.queries.portfolio_queries import (
    count_orders_since,
    get_active_watchlist,
    get_latest_analysis_ts,
    get_top_ranked_signals,
    list_portfolios,
)
from backend.db.session import async_session
from backend.scheduler.schedule import JOB_SCHEDULE
from backend.trading.broker_factory import make_broker
from backend.trading.portfolio_manager import PortfolioManager

logger = logging.getLogger(__name__)

_ANALYSIS_LOOKBACK_DAYS = 400
# Below this many stored bars a symbol is backfilled over the full lookback window
# instead of just appending today (comfortably above the longest indicator period).
_MIN_HISTORY_BARS = 60
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
                reports.append(await ingest_daily_bars(session, current, today, today))
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
            await session.commit()
            outcome.detail = {
                "symbols_scored": len(scores),
                "strategy_version": engine.strategy_version,
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
                    ),
                )
                for i, s in enumerate(signals)
            ]
            engine = DefaultAnalysisEngine()
            midnight = _today_utc_midnight()
            total_orders = 0
            per_portfolio: dict[str, int] = {}
            skipped: list[int] = []
            for portfolio in portfolios:
                # Per-portfolio idempotency: don't double-trade one already traded today.
                if await count_orders_since(session, portfolio.id, midnight) > 0:
                    skipped.append(portfolio.id)
                    continue
                broker = make_broker(
                    session, portfolio.id, strategy_version=engine.strategy_version
                )
                manager = PortfolioManager(broker, session, portfolio.id)
                orders = await manager.execute_signals(ranked)
                per_portfolio[str(portfolio.id)] = len(orders)
                total_orders += len(orders)
            await session.commit()
            outcome.detail = {
                "orders": total_orders,
                "per_portfolio": per_portfolio,
                "skipped_already_traded": skipped,
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
            for portfolio in portfolios:
                broker = make_broker(session, portfolio.id)
                manager = PortfolioManager(broker, session, portfolio.id)
                await manager.update_positions()
                snapshot = await manager.snapshot_nav()
                navs[str(portfolio.id)] = str(snapshot.total)
            await session.commit()
            outcome.detail = {"nav_total_by_portfolio": navs}


JOBS: dict[str, Callable[[], Awaitable[None]]] = {
    "fetch_market_data": fetch_market_data,
    "run_analysis": run_analysis,
    "execute_paper_trades": execute_paper_trades,
    "update_portfolio_nav": update_portfolio_nav,
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
