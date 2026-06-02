<!-- Agent: Agents Orchestrator | Phase: QA | Depends on: Reality Checker, Code Reviewer, Security Engineer, Database Optimizer, Backend Architect, Frontend Developer, Analytics Reporter -->

# Full Audit Report — Autonomous Trader

Consolidated, deduplicated findings from a 7-agent read-only audit. Ranked by a
single severity scale. Each item: source agent(s), evidence `file:line`, problem,
proposed fix. "Necessary fix" vs "enhancement (Phase 1 scope)" is marked.

## Project state (verified, not as-documented)

- Phases 0–5 effectively complete: full docs, 70 backend files, full SvelteKit
  frontend, Docker (prod+dev), 5 migrations, multi-portfolio, fractional shares,
  watchlist seed. `BrokerAdapter` seam intact and never bypassed (except finding C1).
- Implemented for real: technical signals only (RSI/MA/ATR) and 4 of 7 daily jobs
  (`fetch_market_data → run_analysis → execute_paper_trades → update_portfolio_nav`).
  `fetch_macro_data`/`fetch_news_sentiment`/`fetch_fundamentals` and the
  fundamental/macro/sentiment signal modules are clean stubs (intentional).
- Largest gaps: **0 automated tests**, **no CI**, performance/analytics layer not
  delivery-ready, documentation drift behind post-Phase-5 code.

---

## CRITICAL

- **CR1 — Performance endpoint output is unparseable by the UI in normal steady state.**
  (Analytics) `backend/api/main.py:56`, `backend/analysis/performance/metrics.py:316,477-484`,
  `frontend/src/lib/api/client.ts:70`. Once ≥2 NAV rows exist, `summarize_performance`
  emits `NaN` (alpha/beta/benchmark, always — no benchmark) and `inf` (profit_factor).
  Stdlib `json.dumps` emits bare `NaN`/`Infinity`; `JSON.parse` throws → `/portfolio`
  performance card permanently errors. **Fix:** use `ORJSONResponse` (serializes
  non-finite → `null`) or sanitize non-finite floats → `None` at the API boundary.
- **CR2 — `mock_real` broker breaks the swap guarantee: cash is read from the DB ledger,
  bypassing the adapter.** (Code) `backend/trading/portfolio_manager.py:43-47`.
  `_account_balance()` takes `total` from `broker.get_account_balance()` but recomputes
  `cash` via `compute_cash(session, portfolio_id)` and `equity = total - cash`.
  `MockRealBroker` never writes the DB ledger → `cash`/`equity` don't sum to `total`,
  and `RiskManager` sizes against wrong numbers under `mock_real`. **Fix:** source cash
  from the broker too (PortfolioManager must never reach around the adapter into the ledger).
- **CR3 — NAV/equity silently freezes a position's mark at `avg_cost` when a symbol has no
  recent bar.** (Code) `backend/trading/paper_broker.py:197`, `portfolio_manager.py:95,111`,
  `routers/portfolio.py:45,49`. A stale/missing price reports unrealized P&L = 0 and NAV
  unchanged instead of flagging the gap, corrupting the headline metric. **Fix:** carry the
  last persisted `current_price` from `portfolio_positions`, or record the gap in NAV detail.
- **CR4 — Migration 0005 recreates the continuous aggregate `WITH NO DATA` and never
  backfills.** (DB) `backend/db/migrations/versions/0005_multi_portfolio.py:167-169`.
  `weekly_performance` returns no rows until the next policy run (up to 7 days) and
  permanently excludes NAV history older than 90 days on in-place upgrade. **Fix:**
  `CALL refresh_continuous_aggregate('weekly_performance', NULL, NULL);` after recreation
  (and in downgrade).

---

## HIGH

- **H1 — `benchmark_value` is never written → alpha/beta permanently `nan`, SPY overlay dead.**
  (Analytics) `backend/trading/portfolio_manager.py:115-126`. `snapshot_nav` omits
  `benchmark_value` on insert and in the on-conflict `set_`; chart and metrics read it.
  **Fix:** write the SPY close (normalized to contributed base) into `benchmark_value`.
- **H2 — Trade idempotency guard counts REJECTED orders → portfolio can be locked out for the
  day.** (Code) `backend/scheduler/jobs.py:254`, `db/queries/portfolio_queries.py:142-151`,
  `paper_broker.py:134-156`. A first run that only produced rejections marks the portfolio
  "already traded". **Fix:** filter the guard to `status='filled'`.
- **H3 — One shared session across all portfolios → a mid-loop failure rolls back prior
  portfolios' fills.** (Code) `backend/scheduler/jobs.py:221-264`. **Fix:** commit per
  portfolio (or SAVEPOINT per portfolio) for true per-portfolio isolation.
- **H4 — Unvalidated `symbol` interpolated into outbound URL path (path injection / limited
  SSRF).** (Security, Code) `backend/api/routers/market.py:26,34-36` →
  `data_ingestion/providers/yfinance_provider.py:152,181` (`_CHART_URL.format(symbol=...)`).
  `/quotes` and `/bars/{symbol}` skip the `_SYMBOL_RE` that `WatchlistCreate` enforces.
  **Fix:** validate each symbol against `_SYMBOL_RE` (422 on mismatch).
- **H5 — `/api/market/quotes` unbounded symbol list → sequential outbound fan-out DoS.**
  (Security) `backend/api/routers/market.py:26-31`, `yfinance_provider.py:139-145` (30s each).
  **Fix:** cap the parsed, deduped list (e.g. reject >50 with 422).
- **H6 — `data_completeness` computed but never persisted → low-coverage gate can't apply
  after reload.** (Code) `composite_scorer.py:75`, `scoring/persistence.py:52-62`,
  `db/models.py:141-152`, `symbol_ranker.py:42`. **Fix:** add a column and persist/read it,
  or document the gate as analysis-time only.
- **H7 — `strategy_version` width mismatch: `String(64)` (trade_orders) vs `String(48)`
  (algorithm_signals).** (DB) `db/models.py:132` vs `:150`; DDL `0001:119` vs `0003:21`.
  **Fix:** standardize to `String(64)`; migration to widen `algorithm_signals`.
- **H8 — Clickable table rows are not keyboard-accessible.** (Frontend) `routes/+page.svelte:280,319`,
  `trades/+page.svelte:99`, `market/+page.svelte:99-103,110`, `portfolio/+page.svelte:107`.
  `<tr onclick>` with no role/tabindex/keydown. **Fix:** real `<a href>`/`<button>` or
  `tabindex=0`+`role`+`onkeydown`.
- **H9 — No request timeout anywhere in the frontend API layer.** (Frontend) `lib/api/client.ts:43-48`.
  A stalled yfinance call hangs a resource indefinitely (`inFlight` blocks refreshes).
  **Fix:** `AbortController` with configurable timeout → `ApiError('TIMEOUT', …)`.
- **H10 — Index gaps.** (DB) `compute_cash`/`get_filled_orders` use `func.lower(status)='filled'`
  (non-indexable) — `db/queries/portfolio_queries.py:75-87,97-119`; `get_recent_job_runs`
  has no `(started_at DESC)` index — `system_queries.py`. **Fix:** store status lowercased +
  partial index `WHERE status='filled'`; add `ix_job_runs_started`.
- **H11 — Signal-quality metrics computed but orphaned and unfed.** (Analytics)
  `metrics.py:353-438` (`signal_accuracy`, hit-rate-by-sector, holding-period profitability):
  no endpoint calls them and `algorithm_signals.realized_return`/`outcome` are never
  backfilled (no settle job). **Fix:** add a settle step + wire an endpoint, or defer
  explicitly (enhancement).

---

## MEDIUM

- **M1 — `POST /api/system/run` single-flight flag can wedge `True` permanently.** (Security, Code)
  `backend/api/routers/system.py:23-47`. Plain module global, TOCTOU, reset only in task
  `finally`; if task scheduling is dropped the flag never clears. **Fix:** set the flag inside
  the task body and/or gate on the latest `job_runs` row so a stale flag self-heals.
- **M2 — Provider session-date keying can disagree across the yfinance→twelve_data fallback.**
  (Code) `yfinance_provider.py:42-44` vs `twelve_data_provider.py:58-60`, defeating `(symbol, ts)`
  upsert idempotency near UTC boundaries. **Fix:** normalize both to the exchange session date.
- **M3 — Withdraw cash-check is a TOCTOU race; deposit has no upper bound.** (Security)
  `routers/portfolios.py:137-145`, `api/schemas.py:42,65-67`. **Fix:** `SELECT … FOR UPDATE`
  on the portfolio in the same tx; add a sane `le=` bound on `amount`/`initial_deposit`.
- **M4 — Dashboard shows fewer KPIs than the checklist claims; no period-over-period.** (Analytics)
  `frontend/src/routes/+page.svelte` has no Sharpe/Max-Drawdown; no WTD/MTD/YTD/Inception
  switcher, no per-symbol/sector P&L attribution. Daily "change" is actually inception-to-date.
  **Fix:** treat as enhancement (reporting layer).
- **M5 — Realized P&L per trade not surfaced.** (Analytics) `build_round_trips` computes per-trip
  `pnl` but `TradeRecord`/`GET /api/trades` omit `realized_pnl`/`cost_basis`/`signal_score`.
- **M6 — Active-portfolio switch forces a full page reload.** (Frontend) `stores/activePortfolio.ts:25`.
  Heavy on the Pi. **Fix:** reactive store + re-run resources without hard reload.
- **M7 — Scoring chattiness / N+1.** (DB) `compute_cash` + `compute_contributed_capital` =
  2 round-trips × N portfolios on Run now. **Fix:** single query with both aggregates / GROUP BY.
- **M8 — Frontend dashboard `quotes` resource double-fetches and 422s on empty symbols.** (Frontend)
  `routes/+page.svelte:26-32`. **Fix:** guard empty list, drop the redundant `$effect` refresh.
- **M9 — `marketPollMs()` evaluated once; cadence never adapts across session open/close.** (Frontend)
  `routes/market/+page.svelte:13`. **Fix:** re-evaluate inside a self-scheduling tick.
- **M10 — `run_analysis` peak RAM unverified on Pi 4.** (Reality Checker) `scheduler/jobs.py:55,185-199`,
  scheduler `mem_limit: 512m`. Up to 500 symbols × 400 bars in pandas. **Fix:** load-test peak RSS;
  chunk the per-symbol loop if near cap.

---

## LOW / DOC DRIFT

- **D1 — Architecture docs lag the code** (Backend Architect H1/H2/M3/M4/M5): `BrokerAdapter`
  documented sync/`int` but is async/`Decimal`; `mock_real` documented "not registered" but is;
  `STARTING_CASH` no longer drives paper cash; endpoint tables in `module-contracts.md`/
  `backend-services.md` omit the `portfolios`/`system/run`/watchlist/`quotes` routes. **Fix:** docs only.
- **L-misc** (Frontend) dead formatters `format.ts:30,50`; `location.href` full-reload rows;
  index-keyed `recent_errors` list; native `prompt/confirm` dialogs. (Code) `mock_real_broker.py:120`
  bracket access can `KeyError`; partial fills unmodeled; single-day `validate_batch` noise.

---

## Cross-cutting gaps (not a single line — program-level)

- **No automated tests.** No `pytest` (backend) or `vitest`/`playwright` (frontend) anywhere
  in the repo. Highest-leverage quality investment given the financial-math surface.
- **No CI.** No `.github/workflows`. Lint + tests + frontend build should gate every change,
  ARM64-aware.

## Handoff notes

- **Produced:** this consolidated report.
- **Next agent needs to know:** CR1–CR4 corrupt or block the headline metrics and the broker-swap
  guarantee — fix first. H4/H5 are real security defects from post-Phase-5 endpoints. Many MEDIUM
  items are polish; M4/M5/H11 and the missing 3 ingestion jobs are *enhancements*, not fixes —
  keep them clearly separated and inside Phase 1 scope (no real broker, no auth, no multi-user).
- **Deferred decisions:** whether to build the analytics/reporting layer and the
  macro/news/fundamentals ingestion now or later (awaiting owner approval).
