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
| API | `backend/api/main.py`, `deps.py`, `schemas.py`, `routers/{portfolio,portfolios,market,trades,algorithms,system}.py` |
| Scheduler | `backend/scheduler/{jobs.py,main.py,schedule.py}` |
| DB | `db/models.py` (+`JobRun`), `db/migrations/versions/0004_job_runs.py`, query helpers in `db/queries/{portfolio,market,system}_queries.py` |
| Deps | `backend/requirements-api.txt` |

## 2. API surface

No auth, JSON, prefix `/api`. Mostly read-only `GET`; the multi-portfolio +
on-demand-run features (post-Phase-5) add writing endpoints (portfolio CRUD, cash
movements, watchlist edits, manual run). Verified against `backend/api/routers/`.

| Method · Path | Response | Backing |
|---|---|---|
| `GET /portfolio/summary` | `PortfolioSummary` | `compute_cash` + `compute_contributed_capital` + positions + latest bars |
| `GET /portfolio/positions` | `list[Position]` | `get_open_positions` |
| `GET /portfolio/nav?start&end` | `list[PortfolioSnapshot]` | `get_nav_history` |
| `GET /portfolio/performance?start&end` | `PerformanceMetrics` | `get_nav_history` + `get_filled_orders` → `summarize_performance` |
| `GET /portfolios` | `list[PortfolioSchema]` | `list_portfolios` |
| `POST /portfolios` | `PortfolioSchema` (201) | `create_portfolio` (seeds initial deposit) |
| `PATCH /portfolios/{id}` | `PortfolioSchema` | `rename_portfolio` |
| `DELETE /portfolios/{id}` | `{status, id}` | `delete_portfolio` (guards last portfolio) |
| `POST /portfolios/{id}/deposit` | `CashMovementSchema` (201) | `add_cash_movement("deposit")` |
| `POST /portfolios/{id}/withdraw` | `CashMovementSchema` (201) | `add_cash_movement("withdrawal")` (cash-check under row lock) |
| `GET /portfolios/{id}/movements` | `list[CashMovementSchema]` | `get_cash_movements` |
| `GET /market/quotes?symbols` | `list[QuoteEntry]` | live `YFinanceProvider.fetch_live_prices` |
| `GET /market/bars/{symbol}?start&end` | `list[OHLCVBar]` | `get_bars_range` |
| `GET /market/watchlist` | `list[WatchlistEntry]` | `get_active_watchlist` + latest bars + latest signals |
| `POST /market/watchlist` | `WatchlistEntry` (201) | `upsert_watchlist_symbol` |
| `DELETE /market/watchlist/{symbol}` | `WatchlistEntry` | `deactivate_watchlist_symbol` |
| `GET /trades?symbol&start&end&limit` | `list[TradeRecord]` | `get_filtered_orders` |
| `GET /trades/round-trips` | `list[TradeRoundTrip]` | `get_filled_orders` → `build_round_trips` |
| `GET /algorithms/signals?asof&limit` | `list[SignalEntry]` | `get_top_ranked_signals` |
| `GET /algorithms/accuracy` | `SignalAccuracySummary` | `get_settled_signals` → `signal_accuracy` |
| `GET /algorithms/experiments` | `list[ExperimentEntry]` | `ExperimentComparator.list_runs` |
| `POST /system/run` | `RunTrigger` | runs the 4-job pipeline in background (single-flight guarded) |
| `GET /system/status` | `SystemStatus` | `get_last_run_per_job` + static `JOB_SCHEDULE` for next-run |
| `GET /health` | `{"status":"ok"}` | — |

> Path-style choices vs `module-contracts.md` §4: `/market/bars/{symbol}` (path param),
> `/algorithms/signals` (vs `/ranked`). Read-only portfolio reads accept an optional
> `portfolio_id` query param (`resolve_portfolio`) — the active portfolio is chosen
> client-side. Both docs are now aligned on the same endpoint set.

## 3. Key design decisions

- **Cash is ledger-derived, never stored.** `cash = Σ deposits − Σ withdrawals −
  Σ(buy price·qty) + Σ(sell price·qty)` over the `cash_movements` and filled
  `trade_orders` ledgers (`compute_cash`, per-portfolio). `STARTING_CASH` does **not**
  drive paper cash — real budgets live in `cash_movements` (CLAUDE.md multi-portfolio
  note). No mutable cash row; reconstructable after any restart. `portfolio_nav` is a
  daily snapshot only.
- **The `BrokerAdapter` Protocol is `async` with `qty: Decimal`** (and an added
  `async get_cash() -> Decimal`), matching every adapter — CLAUDE.md blesses async +
  Decimal. The whole stack is async SQLAlchemy and a real adapter would be
  network-bound/async too. `PortfolioManager` builds its `AccountBalance` from
  `get_account_balance()` (total) + `get_cash()` (cash), never the DB ledger directly,
  so it reconciles even for the in-memory `MockRealBroker`. `runtime_checkable`
  isinstance still passes.
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
| `STARTING_CASH` | `500` | `MockRealBroker` in-memory starting cash only (paper cash is `cash_movements`-derived) |
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

---

## Update notes

**2026-06-02** — reconciled this doc with the real code (verified against `backend/trading/*` and `backend/api/routers/*`):
- **§3** — the `BrokerAdapter` Protocol is **async with `qty: Decimal`** (plus `async get_cash()`), not "sync shape, byte-for-byte"; CLAUDE.md blesses async + Decimal. `PortfolioManager` assembles `AccountBalance` from `get_account_balance()` + `get_cash()`, never the DB ledger directly (keeps `MockRealBroker` consistent). Cash is derived from the `cash_movements` ledger (`compute_cash`), not `STARTING_CASH`.
- **§2 / §1** — refreshed the endpoint table to the real routers (`portfolio`, `portfolios`, `market`, `trades`, `algorithms`, `system`): added portfolio CRUD + deposit/withdraw/movements, `system/run`, `market/quotes`, `trades/round-trips`, `algorithms/accuracy`.
- **§4 / handoff** — `STARTING_CASH` only seeds `MockRealBroker`. `mock_real` is **registered** in `broker_factory.py`, so the env-only swap gate is satisfied (was previously noted as not registered).

**2026-06-08** — per-portfolio strategy version (A/B) + loss-diagnosis fixes:
- **Per-version trading.** `execute_paper_trades` now groups active portfolios by `strategy_label`,
  scores each distinct version once (`_ranked_for_engine` over the same stored bars) and trades every
  portfolio under **its own** `StrategyConfig`, tagging `trade_orders.strategy_version`. `protective_sell`
  resolves stop params (ATR multiple, min-distance floor) per portfolio. `PortfolioManager` takes an
  optional `config` and applies P2 re-entry cooldown + P6 no-pyramiding entry guards. **Seam intact** —
  `config` is a constructor arg, never part of `place_order`.
- **New endpoints/schemas.** `GET /api/strategies` (lists `config/strategies/*` versions + their
  `strategy_version`). `PATCH /api/portfolios/{id}` now accepts `name` and/or `strategy_label`
  (`PortfolioUpdate`, partial via `model_fields_set`; unknown label → 400). `Portfolio` carries `strategy_label`.
- **Benchmark (P9).** `snapshot_nav`/`_benchmark_value` now anchor on the first real SPY bar at/after
  inception (`get_close_after`); `update_portfolio_nav` skips non-trading days (no stale weekend marks).
- **P8.** `PaperBroker._apply_sell` zeroes `unrealized_pnl` when a position goes flat.
- Full rationale: `docs/diagnostics/01-diagnostico-perdidas.md` / `02-plan-mejora.md`; next steps: `03-plan-v3.md`.

**Open items / deferred**
- **`mock_real` broker** is **registered** in `broker_factory.py` (`_REGISTRY = {"paper": PaperBroker, "mock_real": MockRealBroker}`), so the Reality Checker's env-only swap gate (`BROKER_ADAPTER=mock_real`) is satisfied. A real `alpaca` adapter remains Phase 2.
- **Benchmark NAV** (`portfolio_nav.benchmark_value`) is computed (SPY, rebased) — the earlier "left None" note is obsolete; remaining benchmark work (idempotent backfill of the historical series) is noted in `02-plan-mejora.md` §P9.
- **`get_market_sentiment`** query was added (module-contracts open-Q1) but no `/market/sentiment` endpoint is in the prompt's 10 — exposed query is ready if the dashboard wants it.
- Runtime import of the pydantic/pandas/fastapi layers needs the Python 3.12 image (current `.venv-db` is DB-only on 3.10 — `StrEnum`/pydantic absent). DB query layer was runtime-validated; the rest is byte-compiled. DevOps must install `requirements-api.txt`.
