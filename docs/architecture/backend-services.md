<!-- Agent: Backend Architect | Phase: 4 | Depends on: module-contracts.md, workflow-tree.md, performance-metrics.md, data_ingestion/, db/ -->

# Backend Services — Autonomous Trader

The Phase-4 core: paper broker, portfolio manager, risk manager, the FastAPI
dashboard API, and the four daily scheduler jobs. Everything below respects the
sacred `BrokerAdapter` seam, the DB-only inter-service rule, and "no hardcoded
values" (all parameters are env/config).

---

## 1. What was produced

| Area | Files |
|---|---|
| Trading | `backend/trading/paper_broker.py`, `portfolio_manager.py`, `risk_manager.py` (filled), `broker_factory.py` |
| API | `backend/api/main.py`, `deps.py`, `schemas.py`, `routers/{portfolio,market,trades,algorithms,system}.py` |
| Scheduler | `backend/scheduler/{jobs.py,main.py,schedule.py}` |
| DB | `db/models.py` (+`JobRun`), `db/migrations/versions/0004_job_runs.py`, query helpers in `db/queries/{portfolio,market,system}_queries.py` |
| Deps | `backend/requirements-api.txt` |

## 2. API surface (the launch-prompt's 10 endpoints)

All read-only `GET`, no auth, JSON. Prefix `/api`.

| Path | Response | Backing query |
|---|---|---|
| `/portfolio/summary` | `PortfolioSummary` | cash ledger + positions + latest bars |
| `/portfolio/positions` | `list[Position]` | `get_open_positions` |
| `/portfolio/nav?start&end` | `list[PortfolioSnapshot]` | `get_nav_history` |
| `/portfolio/performance?start&end` | `PerformanceMetrics` | `get_nav_history` + `get_filled_orders` → `summarize_performance` |
| `/trades?symbol&start&end&limit` | `list[TradeRecord]` | `get_filtered_orders` |
| `/market/bars/{symbol}?start&end` | `list[OHLCVBar]` | `get_bars_range` |
| `/market/watchlist` | `list[WatchlistEntry]` | `get_active_watchlist` + latest bars + latest signals |
| `/algorithms/signals?asof&limit` | `list[SignalEntry]` | `get_top_ranked_signals` |
| `/algorithms/experiments` | `list[ExperimentEntry]` | `ExperimentComparator.list_runs` |
| `/system/status` | `SystemStatus` | `get_last_run_per_job` + static `JOB_SCHEDULE` for next-run |
| `/health` | `{"status":"ok"}` | — |

> Divergence from `module-contracts.md` §4: I implemented the **launch-prompt** path
> set (the activation mission), which uses `/market/bars/{symbol}` (path param),
> `/algorithms/signals` (vs `/ranked`), and adds `/portfolio/summary`,
> `/algorithms/experiments`, `/system/status`. The architect's query-aligned set is a
> subset; the Frontend Developer should target the table above.

## 3. Key design decisions

- **Cash is ledger-derived, never stored.** `cash = STARTING_CASH − Σ(buy)·+Σ(sell)`
  over filled `trade_orders` (`compute_cash_from_ledger`). No mutable cash row;
  reconstructable after any restart. `portfolio_nav` is a daily snapshot only.
- **`PaperBroker` methods are `async`; the `BrokerAdapter` Protocol stays
  byte-for-byte sacred (sync shape, untouched).** The whole stack is async SQLAlchemy
  and a real adapter would be network-bound/async too. `runtime_checkable` isinstance
  still passes. This is the one deliberate accommodation — flagged for the Reality Checker.
- **`order_type` is accepted but not persisted** (Phase 1 is market-only; the
  `trade_orders` table has no `order_type` column — module-contracts open-Q3). Slippage
  applies to every fill regardless.
- **Fill model:** same-day latest close × `(1 ± SLIPPAGE_PCT)` (buys +, sells −),
  instant `FILLED`. Sells require sufficient held shares else `REJECTED` (no shorting).
- **Day-level idempotency** for `execute_paper_trades` via `count_orders_since(midnight)`
  — re-running the same day is a no-op (skips), avoiding a schema change to add a
  per-date order key. `snapshot_nav` upserts on a normalized midnight-UTC `ts`.
- **`job_runs` table added** (migration 0004) to back `/system/status` — the workflow
  doc §6 anticipated this table; Backend Architect co-owns trading/health tables.
- **Scheduler ↔ API decoupling:** `/system/status` derives next-run from the static
  `JOB_SCHEDULE` constant (no cross-process call); last-run/status/error from `job_runs`.

## 4. New environment variables (for DevOps `.env.example`)

These extend module-contracts §5. All have safe defaults; none is a secret.

| Var | Default | Used by |
|---|---|---|
| `SLIPPAGE_PCT` | `0.001` | PaperBroker fill price |
| `STARTING_CASH` | `100000` | cash ledger base |
| `MAX_POSITION_PCT` | `0.05` | RiskManager sizing |
| `MAX_OPEN_POSITIONS` | `10` | RiskManager cap |
| `MIN_CASH_PCT` | `0.20` | RiskManager dry-powder reserve |
| `SCHEDULER_DB_URL` | derived from `DATABASE_URL` (`+asyncpg`→`+psycopg`) | APScheduler job store (needs a **sync** driver) |

---

## Handoff notes

**What I produced:** see §1. Endpoints in §2, decisions in §3, new env vars in §4.

**For the AI Engineer**
- `run_analysis` (`scheduler/jobs.py`) already calls `DefaultAnalysisEngine.compute_indicators` / `score_symbol` and persists via `persist_signal_values` + `persist_algorithm_signals`. When you flesh out the scorer/indicators, keep `score_symbol(symbol, bars, asof) -> SymbolScore` and `compute_indicators(...) -> list[IndicatorResult]` signatures — the job depends on them unchanged.
- Bars reach the engine as a pandas frame with lowercase `open/high/low/close/volume` columns indexed by `ts` (see `_bars_to_frame`). Match that in indicators.
- `SymbolScore.action` drives trading: only `SignalAction.BUY` rows are executed. Emit `HOLD`/`SELL` deliberately. Exit logic (generating sells) is not yet wired into `execute_signals` — currently buy-only; coordinate if you want managed exits.
- `strategy_version` is stamped on every order and signal from `DefaultAnalysisEngine.strategy_version` — your config changes auto-version via `config_hash`.

**For the Frontend Developer**
- Target the §2 endpoint table (not module-contracts §4). All responses are JSON; money/price/score fields are decimal strings — parse as numbers.
- `/portfolio/performance` returns `{returns, risk, trades}` dicts of floats (keys per `reporting-structure.md`); `trades` is empty until there are closed round trips.
- `/system/status` gives per-job `status` (success/degraded/skipped/failed), `last_run_at`, `next_run_at`, and a `recent_errors` list — enough for a red/amber/green health panel.
- `/market/watchlist` already joins latest price + latest score/action per symbol; `/algorithms/signals` carries `reason` and `indicator_snapshot` for the signal-breakdown view.
- The API serves the built SvelteKit site from `frontend/build` at `/` when that dir exists (single container). Same-origin by default; set `CORS_ALLOW_ORIGINS` only for a separate dev origin.

**Open items / deferred**
- **`mock_real` broker** for the Reality Checker's env-swap gate is not registered (Phase 2 / out of scope). The seam is ready: add one line to `_REGISTRY` in `broker_factory.py`.
- **Benchmark NAV** (`portfolio_nav.benchmark_value`) is left `None`; alpha/beta need a benchmark series — wire a benchmark symbol into `snapshot_nav` when desired.
- **`get_market_sentiment`** query was added (module-contracts open-Q1) but no `/market/sentiment` endpoint is in the prompt's 10 — exposed query is ready if the dashboard wants it.
- Runtime import of the pydantic/pandas/fastapi layers needs the Python 3.12 image (current `.venv-db` is DB-only on 3.10 — `StrEnum`/pydantic absent). DB query layer was runtime-validated; the rest is byte-compiled. DevOps must install `requirements-api.txt`.
