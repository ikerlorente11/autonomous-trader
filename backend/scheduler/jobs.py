"""The four daily compute/ingestion jobs.

Two classes (workflow-tree.md §intro): ingestion jobs call external APIs and write
raw data; compute jobs read **only** from the DB and never touch the network. Every
job is idempotent, guarded by the market calendar, emits one structured-JSON line per
lifecycle event to stdout (Docker captures it), and records a ``job_runs`` row for the
dashboard health panel. Failures are recorded and swallowed so a dead source degrades
the day rather than crashing the scheduler.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analysis.config import load_strategy_config
from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator
from backend.analysis.micro.universe import select_micro_universe
from backend.analysis.performance.settle import settle_due_signals
from backend.analysis.scoring.persistence import (
    persist_algorithm_signals,
    persist_signal_values,
)
from backend.analysis.signals.fundamental.signals import compute_fundamental_signals
from backend.analysis.signals.macro.regime import (
    MACRO_REGIME_SIGNAL_ID,
    RegimeResult,
    classify_from_macro,
    regime_series_ids,
)
from backend.analysis.signals.sentiment.news import (
    NEWS_BUZZ_SIGNAL_ID,
    news_buzz_score,
)
from backend.contracts import (
    IndicatorResult,
    OHLCVBar,
    OrderState,
    RankedSymbol,
)
from backend.data_ingestion.calendar import (
    is_market_open_now,
    is_near_market_close,
    is_trading_day,
    nth_prior_trading_day,
    previous_trading_day,
    trading_days,
)
from backend.data_ingestion.fundamentals_ingest import (
    fundamentals_data_configured,
    ingest_fundamentals,
)
from backend.data_ingestion.ingest import ingest_daily_bars, upsert_bars
from backend.data_ingestion.intraday_ingest import (
    ingest_intraday_bars,
    micro_bar_interval,
    micro_lookback_days,
    micro_max_symbols,
)
from backend.data_ingestion.macro_ingest import (
    ingest_macro_series,
    macro_data_configured,
    macro_lookback_days,
    macro_series_ids,
)
from backend.data_ingestion.news_ingest import (
    ingest_news_sentiment,
    news_data_configured,
    news_lookback_days,
)
from backend.data_ingestion.providers.yfinance_provider import YFinanceProvider
from backend.db.models import JobRun
from backend.db.queries.fundamentals_queries import get_recent_fundamentals
from backend.db.queries.macro_queries import get_latest_macro_values
from backend.db.queries.market_queries import (
    bar_coverage_by_session,
    count_bars_per_symbol,
    get_bars_range,
    get_intraday_bars_range,
    get_latest_bars,
)
from backend.db.queries.news_queries import get_recent_news_counts
from backend.db.queries.portfolio_queries import (
    count_filled_orders_since,
    get_active_watchlist,
    get_latest_analysis_ts,
    get_open_positions,
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
# How far back the incremental fetch looks for holes to heal. The trailing window
# above is blind to a session lost while the scheduler was down: catching up moves
# the window past the hole and it stays missing forever (2026-08-04 blackout left
# Aug 4-6 empty and Aug 3 at 1/62 symbols, silently shifting every indicator's
# session count). Below, any incomplete session inside this window widens the fetch
# back to it. A symbol that legitimately has no bar on some session (halt, late
# listing) keeps the window at its widest — bounded, and the request count per
# symbol is unchanged since the provider fetches a range, not a day.
_GAP_HEAL_LOOKBACK_DAYS = 45
# Must span the whole scored universe, not just buy candidates: the manager also
# reads the low-scored end to find SELL signals on names it currently holds, so a
# larger watchlist must not truncate exits. Comfortably above the 50-symbol target.
_RANK_LIMIT = 500
# The daily pipeline trades only daily-swing portfolios; microtrading portfolios
# (kind='micro') are traded by the future intraday jobs, never here.
_DAILY_KINDS = ("daily",)


def _today_utc_midnight() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _today_utc() -> dt.date:
    # Job gates must agree with the UTC run-id/asof stamps; naive date.today() is
    # container-local and diverges around midnight if TZ is ever set non-UTC.
    return dt.datetime.now(dt.timezone.utc).date()


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


_DEFAULT_JOB_TIMEOUT_SECONDS = 1800


def _job_timeout_seconds(job: str) -> int:
    """Wall-clock cap for one job run; <= 0 disables it.

    No job had a ceiling until 2026-08-31, when a Finnhub outage turned
    ``fetch_news_sentiment`` into an hours-long crawl: every symbol burned its
    retries against a server-sent ``Retry-After``, and the manual pipeline sat behind
    it without ever reaching the trades. An unbounded job is also a job that can still
    be running when tomorrow's copy is due. Overridable per job
    (``JOB_TIMEOUT_SECONDS_FETCH_NEWS_SENTIMENT``) for the rare slow one."""
    for name in (f"JOB_TIMEOUT_SECONDS_{job.upper()}", "JOB_TIMEOUT_SECONDS"):
        raw = os.environ.get(name)
        if raw is not None and raw.strip() != "":
            try:
                return int(raw)
            except ValueError:
                continue
    return _DEFAULT_JOB_TIMEOUT_SECONDS


@asynccontextmanager
async def _job_context(job: str):
    run_id = _today_utc_midnight().isoformat()
    started = dt.datetime.now(dt.timezone.utc)
    t0 = time.monotonic()
    outcome = JobOutcome()
    _log_event(job, "job_start", run_id=run_id)
    error: str | None = None
    limit = _job_timeout_seconds(job)
    try:
        async with asyncio.timeout(limit if limit > 0 else None):
            yield outcome
    except TimeoutError:
        # Recorded as a failure, not a silent truncation: the health check counts
        # failed runs, so a job that hangs now raises the alarm instead of hiding.
        outcome.status = "failed"
        error = f"job exceeded its {limit}s wall-clock limit"
        logger.error("job %s timed out after %ss", job, limit)
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


async def _oldest_incomplete_session(
    session: AsyncSession, symbols: Sequence[str], today: dt.date
) -> dt.date | None:
    """Oldest session in the heal window where some symbol has no stored bar.

    The newest expected session is excluded: this job runs pre-market, so the most
    recent close is precisely what the fetch about to run will bring in — counting it
    as a hole would widen the window every single day."""
    window_start = today - dt.timedelta(days=_GAP_HEAL_LOOKBACK_DAYS)
    expected = trading_days(window_start, previous_trading_day(today))[:-1]
    if not expected:
        return None
    coverage = await bar_coverage_by_session(
        session,
        symbols,
        dt.datetime.combine(window_start, dt.time.min, tzinfo=dt.timezone.utc),
        dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc),
    )
    for day in expected:
        if coverage.get(day, 0) < len(symbols):
            return day
    return None


def _bar_staleness_cutoff(asof: dt.datetime) -> dt.date | None:
    """P12: the oldest acceptable latest-bar date, or None when the gate is disabled.

    ``MAX_BAR_STALENESS_DAYS`` (env, default 0 = off) is how many sessions a symbol may
    fall behind before it is excluded from scoring/execution — guards against deciding
    on stale prices (low € impact today, important for a real broker)."""
    try:
        max_days = int(os.environ.get("MAX_BAR_STALENESS_DAYS", "0"))
    except ValueError:
        max_days = 0
    if max_days <= 0:
        return None
    return nth_prior_trading_day(asof.date(), max_days)


def _bars_fresh(rows, cutoff: dt.date | None) -> bool:
    """True if the symbol's latest bar is recent enough (>= cutoff), or the gate is off."""
    if cutoff is None:
        return True
    return bool(rows) and rows[-1].ts.date() >= cutoff


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
async def fetch_macro_data() -> None:
    async with _job_context("fetch_macro_data") as outcome:
        today = _today_utc()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            _log_event("fetch_macro_data", "MARKET_CLOSED", day=today.isoformat())
            return
        if not macro_data_configured():
            # Optional provider key absent — skip cleanly, don't record a hard failure.
            outcome.status = "skipped"
            outcome.detail = {"reason": "no_api_key"}
            _log_event("fetch_macro_data", "NO_API_KEY")
            return
        series = macro_series_ids()
        start = today - dt.timedelta(days=macro_lookback_days())
        async with async_session() as session:
            written = await ingest_macro_series(session, series, start, today)
        empty = [sid for sid, n in written.items() if n == 0]
        outcome.status = "degraded" if empty else "success"
        outcome.detail = {
            "series_requested": len(series),
            "rows_written": sum(written.values()),
            "series_empty": empty,
        }


async def fetch_news_sentiment() -> None:
    async with _job_context("fetch_news_sentiment") as outcome:
        today = _today_utc()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            _log_event("fetch_news_sentiment", "MARKET_CLOSED", day=today.isoformat())
            return
        if not news_data_configured():
            outcome.status = "skipped"
            outcome.detail = {"reason": "no_api_key"}
            _log_event("fetch_news_sentiment", "NO_API_KEY")
            return
        since = _today_utc_midnight() - dt.timedelta(days=news_lookback_days())
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            symbols = [w.symbol for w in watchlist]
            if not symbols:
                outcome.status = "skipped"
                outcome.detail = {"reason": "empty_watchlist"}
                return
            written = await ingest_news_sentiment(session, symbols, since)
        empty = [s for s, n in written.items() if n == 0]
        outcome.status = "degraded" if empty else "success"
        outcome.detail = {
            "symbols_requested": len(symbols),
            "rows_written": sum(written.values()),
            "symbols_empty": empty,
        }


async def fetch_market_data() -> None:
    async with _job_context("fetch_market_data") as outcome:
        today = _today_utc()
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
            incremental_start = today - dt.timedelta(days=_INCREMENTAL_LOOKBACK_DAYS)
            if current:
                gap_start = await _oldest_incomplete_session(session, current, today)
                if gap_start is not None and gap_start < incremental_start:
                    incremental_start = gap_start
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
                "incremental_start": incremental_start.isoformat(),
            }


async def fetch_fundamentals() -> None:
    async with _job_context("fetch_fundamentals") as outcome:
        today = _today_utc()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            _log_event("fetch_fundamentals", "MARKET_CLOSED", day=today.isoformat())
            return
        if not fundamentals_data_configured():
            outcome.status = "skipped"
            outcome.detail = {"reason": "no_api_key"}
            _log_event("fetch_fundamentals", "NO_API_KEY")
            return
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            symbols = [w.symbol for w in watchlist]
            if not symbols:
                outcome.status = "skipped"
                outcome.detail = {"reason": "empty_watchlist"}
                return
            written = await ingest_fundamentals(session, symbols)
        empty = [s for s, n in written.items() if n == 0]
        outcome.status = "degraded" if empty else "success"
        outcome.detail = {
            "symbols_requested": len(symbols),
            "rows_written": sum(written.values()),
            "symbols_empty": empty,
        }


# --------------------------------------------------------------------------- #
# Compute jobs (DB-only, no network)
# --------------------------------------------------------------------------- #
async def run_analysis() -> None:
    async with _job_context("run_analysis") as outcome:
        today = _today_utc()
        if not is_trading_day(today):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
        asof = _today_utc_midnight()
        start = asof - dt.timedelta(days=_ANALYSIS_LOOKBACK_DAYS)
        engine = DefaultAnalysisEngine()
        cutoff = _bar_staleness_cutoff(asof)
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            frames: dict[str, pd.DataFrame] = {}
            for entry in watchlist:
                rows = await get_bars_range(session, entry.symbol, start, asof)
                if not rows or not _bars_fresh(rows, cutoff):
                    continue
                frames[entry.symbol] = _bars_to_frame(rows)
            # Fundamentals/news per symbol + the macro regime: persisted in observation
            # mode for every version AND offered to the engine — a version only uses
            # what its config weights (extras) / enables (regime multiplier), so the
            # base composite stays unchanged (P11 activation is config, not code).
            extras, regime = await _universe_extras(session, list(frames), asof)
            # P7: one universe pass — rank-normalizes weighted sub-scores when the config
            # enables it (the base config does not, so the persisted set stays raw).
            indicators, scores = engine.score_universe(
                frames, asof, extra_signals=extras, regime_score=regime.score
            )
            indicators = list(indicators)
            for symbol, extra in extras.items():
                indicators.extend(
                    IndicatorResult(
                        symbol=symbol,
                        ts=asof,
                        signal_id=signal_id,
                        value=Decimal(str(round(value, 8))),
                    )
                    for signal_id, value in extra.items()
                )
            if not scores:
                outcome.status = "degraded"
                outcome.detail = {"reason": "NO_SIGNALS", "symbols_scored": 0}
                _log_event("run_analysis", "NO_SIGNALS")
                return
            if regime.score is not None:
                regime_value = Decimal(str(round(regime.score, 8)))
                indicators.extend(
                    IndicatorResult(
                        symbol=s.symbol,
                        ts=asof,
                        signal_id=MACRO_REGIME_SIGNAL_ID,
                        value=regime_value,
                    )
                    for s in scores
                )
            await persist_signal_values(session, indicators)
            await persist_algorithm_signals(session, scores, engine.strategy_version)
            settled = await settle_due_signals(session, asof)
            await session.commit()
            outcome.detail = {
                "symbols_scored": len(scores),
                "strategy_version": engine.strategy_version,
                "signals_settled": settled,
                "macro_regime": regime.regime,
                "macro_regime_score": (
                    round(regime.score, 2) if regime.score is not None else None
                ),
            }


async def _universe_extras(
    session, symbols: list[str], asof: dt.datetime
) -> tuple[dict[str, dict[str, float]], "RegimeResult"]:
    """Non-bar signals for the universe: fundamentals + news buzz per symbol, plus the
    market-wide macro regime. DB reads only (compute jobs never touch the network).
    One shared computation feeds run_analysis persistence, every version's scoring
    (via ``score_universe(extra_signals=...)``) and the regime multiplier."""
    extras: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        per: dict[str, float] = {}
        fundamentals = await get_recent_fundamentals(session, symbol)
        if fundamentals:
            per.update(
                compute_fundamental_signals([fr.line_items for fr in fundamentals])
            )
        buzz = news_buzz_score(await get_recent_news_counts(session, symbol))
        if buzz is not None:
            per[NEWS_BUZZ_SIGNAL_ID] = buzz
        if per:
            extras[symbol] = per
    regime = classify_from_macro(
        await get_latest_macro_values(session, regime_series_ids(), asof)
    )
    return extras, regime


def _config_for_label(label: str | None):
    """Resolve a portfolio's strategy version to a config. Falls back to the base config
    if the variant file is missing so a portfolio never stops trading on a typo'd label."""
    try:
        return load_strategy_config(label=label) if label else load_strategy_config()
    except FileNotFoundError:
        logger.warning("strategy version %r not found; using base config", label)
        return load_strategy_config()


def _engine_for_label(label: str | None) -> DefaultAnalysisEngine:
    return DefaultAnalysisEngine(_config_for_label(label))


def _execution_config(label: str | None, engine: DefaultAnalysisEngine, frames):
    """The config that governs a portfolio's ENTRY discipline today. Normally the
    version's own; a regime-switch version with ``trading_from_leg`` (v9) adopts the
    ACTIVE LEG's trading knobs — each regime runs the execution style that won it.
    Only execute_paper_trades resolves this (protective stops stay on the version's
    own config: protection is constant, entries adapt)."""
    cfg = _config_for_label(label)
    switch = cfg.regime_switch
    if switch is not None and switch.trading_from_leg:
        leg = engine.active_leg(frames)
        if leg:
            return _config_for_label(leg)
    return cfg


async def _fresh_frames(session, asof: dt.datetime) -> dict[str, pd.DataFrame]:
    """The watchlist's fresh bar frames for one execution pass — loaded ONCE and
    shared by every version's scoring plus the ATR map (vol-targeted sizing)."""
    start = asof - dt.timedelta(days=_ANALYSIS_LOOKBACK_DAYS)
    cutoff = _bar_staleness_cutoff(asof)
    watchlist = await get_active_watchlist(session)
    frames: dict[str, pd.DataFrame] = {}
    for entry in watchlist:
        rows = await get_bars_range(session, entry.symbol, start, asof)
        if not rows or not _bars_fresh(rows, cutoff):
            continue
        frames[entry.symbol] = _bars_to_frame(rows)
    return frames


def _frame_atr_map(frames: Mapping[str, pd.DataFrame]) -> dict[str, Decimal]:
    """Raw ATR(14) per symbol from already-loaded frames — the risk unit for
    vol-targeted sizing (same indicator/period the protective stop uses)."""
    indicator = AverageTrueRangeIndicator(period=_ATR_PERIOD, sensitivity=1.0)
    out: dict[str, Decimal] = {}
    for symbol, df in frames.items():
        if len(df) < _ATR_PERIOD + 1:
            continue
        series = indicator.compute(df).dropna()
        if not series.empty:
            out[symbol] = Decimal(str(float(series.iloc[-1])))
    return out


def _ranked_for_engine(
    engine: DefaultAnalysisEngine,
    frames: Mapping[str, pd.DataFrame],
    asof: dt.datetime,
    extras: dict[str, dict[str, float]] | None = None,
    regime_score: float | None = None,
) -> list[RankedSymbol]:
    """Score the shared frames under one engine's config and return the top signals
    by score (mirrors get_top_ranked_signals, but per strategy version, scored in
    memory from the stored bars instead of the single persisted base set)."""
    # P7: score the whole universe in one pass so rank-normalization (when this version
    # enables it) sees every symbol; mirrors run_analysis via the same engine method.
    _, scores = engine.score_universe(
        frames, asof, extra_signals=extras, regime_score=regime_score
    )
    scores.sort(key=lambda s: s.score, reverse=True)
    return [RankedSymbol(rank=i + 1, score=s) for i, s in enumerate(scores[:_RANK_LIMIT])]


async def execute_paper_trades() -> None:
    async with _job_context("execute_paper_trades") as outcome:
        today = _today_utc()
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
            # If today's run_analysis failed or degraded, the latest analysis is
            # yesterday's — trading on it would rescore stale bars while filling at
            # the latest close. Skip; the misfire/retry path re-runs the pipeline.
            if asof < _today_utc_midnight():
                outcome.status = "skipped"
                outcome.detail = {"reason": "STALE_ANALYSIS", "asof": asof.isoformat()}
                return
            portfolios = await list_portfolios(
                session, active_only=True, kinds=_DAILY_KINDS
            )
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_active_portfolios"}
                return
            # Each distinct strategy version is scored once; portfolios on the same
            # version share its ranked set. v1 vs v2 thus trade different decisions.
            # Extras (fundamentals/news + macro regime) are computed once and shared.
            watchlist = await get_active_watchlist(session)
            extras, regime = await _universe_extras(
                session, [w.symbol for w in watchlist], asof
            )
            frames = await _fresh_frames(session, asof)
            atr_map = _frame_atr_map(frames)
            engines: dict[str | None, DefaultAnalysisEngine] = {}
            ranked_by_label: dict[str | None, list[RankedSymbol]] = {}
            for label in {p.strategy_label for p in portfolios}:
                engine = _engine_for_label(label)
                engines[label] = engine
                ranked_by_label[label] = _ranked_for_engine(
                    engine, frames, asof, extras=extras, regime_score=regime.score
                )
            midnight = _today_utc_midnight()
            total_orders = 0
            per_portfolio: dict[str, int] = {}
            versions: dict[str, str] = {}
            skipped: list[int] = []
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                # Per-portfolio idempotency: don't double-trade one already traded today.
                # Protective-sell fills don't count — an intraday stop-out must not
                # block a later manual run of the daily execution.
                if await count_filled_orders_since(
                    session, portfolio.id, midnight,
                    exclude_strategy_version=_PROTECTIVE_SELL_STRATEGY,
                ) > 0:
                    skipped.append(portfolio.id)
                    continue
                engine = engines[portfolio.strategy_label]
                ranked = ranked_by_label[portfolio.strategy_label]
                versions[str(portfolio.id)] = engine.strategy_version
                # Each portfolio runs in its own savepoint so one failure rolls back only
                # that portfolio, never the fills already booked for the others (H3).
                try:
                    async with session.begin_nested():
                        broker = make_broker(
                            session, portfolio.id,
                            strategy_version=engine.strategy_version,
                        )
                        manager = PortfolioManager(
                            broker, session, portfolio.id,
                            config=_execution_config(
                                portfolio.strategy_label, engine, frames
                            ),
                            atr_by_symbol=atr_map,
                        )
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
                "versions": versions,
                "skipped_already_traded": skipped,
                "failed": failed,
            }


async def update_portfolio_nav() -> None:
    async with _job_context("update_portfolio_nav") as outcome:
        # P9: don't stamp a NAV/benchmark point on non-session days — it carried stale
        # weekend marks forward and skewed the day-by-day benchmark. Market days only.
        if not is_trading_day(_today_utc()):
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
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
            portfolios = await list_portfolios(
                session, active_only=True, kinds=_DAILY_KINDS
            )
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_active_portfolios"}
                return

            atr_start = asof - dt.timedelta(days=_ATR_LOOKBACK_DAYS)
            triggered_total = 0
            per_portfolio: dict[str, int] = {}
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                positions = await get_open_positions(session, portfolio.id)
                if not positions:
                    continue
                # Per-version stop tuning (P3): a wider ATR multiple and/or a minimum
                # distance floor so calm names aren't stopped out by 1–2% noise.
                trading = _config_for_label(portfolio.strategy_label).trading
                p_atr_mult = (
                    Decimal(str(trading.stop_atr_multiple))
                    if trading.stop_atr_multiple is not None
                    else atr_mult
                )
                p_min_dist = (
                    Decimal(str(trading.stop_min_distance_pct))
                    if trading.stop_min_distance_pct is not None
                    else Decimal(0)
                )
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
                # Same per-portfolio savepoint isolation as the other portfolio jobs:
                # one bad position/price must not roll back every portfolio's stops
                # and HWM ratchets for this tick — protection matters most exactly
                # when the data is misbehaving.
                try:
                    async with session.begin_nested():
                        for position in positions:
                            price = live.get(position.symbol)
                            if price is None:
                                continue
                            atr = _latest_atr(
                                await get_bars_range(session, position.symbol, atr_start, asof)
                            )
                            new_hwm, hit = evaluate_trailing_stop(
                                position.avg_cost, position.high_water_mark, price,
                                pct=pct, atr=atr, atr_multiple=p_atr_mult,
                                distance_factor=distance_factor,
                                min_distance_pct=p_min_dist,
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
                except Exception as exc:  # noqa: BLE001 — isolate, record, continue
                    failed[str(portfolio.id)] = repr(exc)
                    logger.exception("protective_sell failed for portfolio %s", portfolio.id)

            await session.commit()
            if failed:
                outcome.status = "degraded"
            outcome.detail = {
                "stops_triggered": triggered_total,
                "trailing_stop_pct": str(pct),
                "atr_multiple": str(atr_mult),
                "vix": str(vix_val) if vix_val is not None else None,
                "panic_hold": panic_hold,
                "per_portfolio": per_portfolio,
                "failed": failed,
            }


async def fetch_intraday_bars() -> None:
    """Poll intraday bars for the microtrading sub-universe during market hours (M1).

    An interval job (like ``protective_sell``), NOT part of the daily JOB_SCHEDULE:
    registered in ``scheduler/main.py`` and gated by ``MICRO_ENABLED``. Idempotent
    upsert, capped sub-universe, degrades when a provider key is absent. Builds the
    forward-test history the micro versions will calibrate against; nothing trades yet."""
    async with _job_context("fetch_intraday_bars") as outcome:
        if not is_market_open_now():
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
        interval = micro_bar_interval()
        lookback = micro_lookback_days()
        async with async_session() as session:
            watchlist = await get_active_watchlist(session)
            all_symbols = [w.symbol for w in watchlist]
            if not all_symbols:
                outcome.status = "skipped"
                outcome.detail = {"reason": "empty_watchlist"}
                return
            # Sub-universe = the most-liquid day-tradeable names (caps free-tier credits
            # + Pi I/O). Degrade to the first N if no daily-bar history exists yet to
            # rank by — the data still flows so liquidity history can build.
            cap = micro_max_symbols()
            symbols = await select_micro_universe(
                session, all_symbols, _today_utc_midnight(), limit=cap
            )
            if not symbols:
                symbols = all_symbols[:cap]
            written = await ingest_intraday_bars(
                session, symbols, interval=interval, lookback_days=lookback
            )
            await session.commit()
        empty = [s for s, n in written.items() if n == 0]
        outcome.status = "degraded" if empty else "success"
        outcome.detail = {
            "interval": interval,
            "symbols_requested": len(symbols),
            "rows_written": sum(written.values()),
            "symbols_empty": empty,
        }


_MICRO_KINDS = ("micro",)
_MICRO_EOD_STRATEGY = "micro_eod_flatten"
_DEFAULT_EOD_FLATTEN_WITHIN_MIN = 10

# run_micro and micro_eod_flatten are independent interval jobs on the same event
# loop; near the close both can see the same live position and both sell it (each
# session's coverage check reads a pre-commit snapshot → duplicate fill → phantom
# cash). One lock serializes every micro trading section.
_MICRO_TRADE_LOCK = asyncio.Lock()


def _micro_eod_flatten_within_min() -> int:
    try:
        return max(1, int(os.environ.get("MICRO_EOD_FLATTEN_WITHIN_MIN", "")))
    except ValueError:
        return _DEFAULT_EOD_FLATTEN_WITHIN_MIN


async def _micro_frames(
    session, symbols: list[str], start: dt.datetime, end: dt.datetime
) -> dict[str, pd.DataFrame]:
    """Intraday OHLCV frames per symbol for micro scoring (same shape as daily frames,
    so the existing engine indicators compute on 5-minute bars unchanged)."""
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        rows = await get_intraday_bars_range(session, symbol, start, end)
        if rows:
            frames[symbol] = _bars_to_frame(rows)
    return frames


async def run_micro() -> None:
    """Score the micro sub-universe on intraday bars and trade every micro portfolio.

    Interval job, market-hours-gated, opt-in (``MICRO_ENABLED``). Reuses the daily
    engine/scorer on 5-minute frames and the unchanged ``BrokerAdapter`` seam (broker +
    manager priced intraday). No once-per-day guard — micro trades repeatedly; churn is
    bounded by no-pyramiding (held names aren't re-bought) and available cash."""
    async with _job_context("run_micro") as outcome:
        if not is_market_open_now():
            outcome.status = "skipped"
            outcome.detail = {"reason": "MARKET_CLOSED"}
            return
        if is_near_market_close(_micro_eod_flatten_within_min()):
            # Entering the flatten window: any buy here would be liquidated seconds
            # later (pure churn), and a signal exit here would race the flatten sell.
            outcome.status = "skipped"
            outcome.detail = {"reason": "EOD_FLATTEN_WINDOW"}
            return
        asof = dt.datetime.now(dt.timezone.utc)
        start = asof - dt.timedelta(days=micro_lookback_days())
        async with _MICRO_TRADE_LOCK, async_session() as session:
            portfolios = await list_portfolios(
                session, active_only=True, kinds=_MICRO_KINDS
            )
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_micro_portfolios"}
                return
            watchlist = await get_active_watchlist(session)
            universe = await select_micro_universe(
                session,
                [w.symbol for w in watchlist],
                _today_utc_midnight(),
                limit=micro_max_symbols(),
            )
            frames = await _micro_frames(session, universe, start, asof)
            if not frames:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_intraday_bars"}
                return
            atr_map = _frame_atr_map(frames)  # 5m ATR — the intraday risk unit
            engines: dict[str | None, DefaultAnalysisEngine] = {}
            ranked_by_label: dict[str | None, list[RankedSymbol]] = {}
            for label in {p.strategy_label for p in portfolios}:
                engine = _engine_for_label(label)
                engines[label] = engine
                _, scores = engine.score_universe(frames, asof)
                scores.sort(key=lambda s: s.score, reverse=True)
                ranked_by_label[label] = [
                    RankedSymbol(rank=i + 1, score=s) for i, s in enumerate(scores)
                ]
            total_orders = 0
            per_portfolio: dict[str, int] = {}
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                engine = engines[portfolio.strategy_label]
                ranked = ranked_by_label[portfolio.strategy_label]
                try:
                    async with session.begin_nested():
                        broker = make_broker(
                            session, portfolio.id,
                            strategy_version=engine.strategy_version, intraday=True,
                        )
                        manager = PortfolioManager(
                            broker, session, portfolio.id,
                            config=_config_for_label(portfolio.strategy_label),
                            intraday=True,
                            atr_by_symbol=atr_map,
                        )
                        orders = await manager.execute_signals(ranked)
                    per_portfolio[str(portfolio.id)] = len(orders)
                    total_orders += len(orders)
                except Exception as exc:  # noqa: BLE001 — isolate, record, continue
                    failed[str(portfolio.id)] = repr(exc)
                    logger.exception("run_micro failed for portfolio %s", portfolio.id)
            await session.commit()
            if failed:
                outcome.status = "degraded"
            outcome.detail = {
                "universe": len(frames),
                "orders": total_orders,
                "per_portfolio": per_portfolio,
                "failed": failed,
            }


async def micro_eod_flatten() -> None:
    """Liquidate every micro position before the close (no overnight micro risk).

    Interval job that acts only in the last ``MICRO_EOD_FLATTEN_WITHIN_MIN`` minutes of
    the session (DST-robust via the exchange calendar). Idempotent: once flat there is
    nothing left to sell on the next tick. Sells via the unchanged ``place_order`` seam."""
    async with _job_context("micro_eod_flatten") as outcome:
        if not is_near_market_close(_micro_eod_flatten_within_min()):
            outcome.status = "skipped"
            outcome.detail = {"reason": "NOT_NEAR_CLOSE"}
            return
        async with _MICRO_TRADE_LOCK, async_session() as session:
            portfolios = await list_portfolios(
                session, active_only=True, kinds=_MICRO_KINDS
            )
            if not portfolios:
                outcome.status = "skipped"
                outcome.detail = {"reason": "no_micro_portfolios"}
                return
            total_sold = 0
            per_portfolio: dict[str, int] = {}
            failed: dict[str, str] = {}
            for portfolio in portfolios:
                try:
                    async with session.begin_nested():
                        broker = make_broker(
                            session, portfolio.id,
                            strategy_version=_MICRO_EOD_STRATEGY, intraday=True,
                        )
                        sold = 0
                        for position in await broker.get_positions():
                            if position.qty > 0:
                                await broker.place_order(
                                    position.symbol, "sell", position.qty, "market"
                                )
                                sold += 1
                    per_portfolio[str(portfolio.id)] = sold
                    total_sold += sold
                except Exception as exc:  # noqa: BLE001 — isolate, record, continue
                    failed[str(portfolio.id)] = repr(exc)
                    logger.exception(
                        "micro_eod_flatten failed for portfolio %s", portfolio.id
                    )
            await session.commit()
            if failed:
                outcome.status = "degraded"
            outcome.detail = {
                "positions_sold": total_sold,
                "per_portfolio": per_portfolio,
                "failed": failed,
            }


JOBS: dict[str, Callable[[], Awaitable[None]]] = {
    "fetch_macro_data": fetch_macro_data,
    "fetch_news_sentiment": fetch_news_sentiment,
    "fetch_market_data": fetch_market_data,
    "fetch_fundamentals": fetch_fundamentals,
    "run_analysis": run_analysis,
    "execute_paper_trades": execute_paper_trades,
    "update_portfolio_nav": update_portfolio_nav,
    "protective_sell": protective_sell,
    "fetch_intraday_bars": fetch_intraday_bars,
    "run_micro": run_micro,
    "micro_eod_flatten": micro_eod_flatten,
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
