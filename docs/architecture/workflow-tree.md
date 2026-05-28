<!-- Agent: Workflow Architect | Phase: 1 | Depends on: docs/research/00-signal-synthesis.md, CLAUDE.md -->

# Workflow Tree — Autonomous Trader

The complete operational map of the system: every job, every branch, every failure path, and every recovery. This is the contract the Backend Architect implements against and DevOps Automator deploys against.

> **Scheduling authority.** Job *times* are the canonical CLAUDE.md sequence (06:00–08:15 UTC). The launch brief's simplified `07:00/07:30/08:00/08:15` view is a subset; this document uses the full fan-out from synthesis §6 layered onto the CLAUDE.md times. All jobs: `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`. APScheduler uses a **PostgreSQL job store** (CLAUDE.md) so the schedule survives reboots.

> **Two job classes.** *Ingestion* jobs (06:00–06:45) call external APIs and write raw/normalized data to DB. *Compute* jobs (07:30–08:15) read **only** from DB, never call an external API. This separation is the backbone of every failure-recovery decision below: a dead external API can only break ingestion, never analysis or trade execution.

---

## 1 — Daily job sequence (happy path)

```
06:00 UTC  fetch_macro_data        FRED series (13) + nothing else external
06:15 UTC  fetch_news_sentiment    Finnhub company-news + CBOE put/call CSV + EDGAR 8-K/Form-4 scan
06:30 UTC  fetch_market_data       yfinance OHLCV: 50 watchlist + ~16 macro/intermarket tickers
06:45 UTC  fetch_fundamentals      yfinance quarterly stmts + earnings dates; short-interest on publish days
07:30 UTC  run_analysis            reads ALL categories from DB → composite score → signal_values
08:00 UTC  execute_paper_trades    ranked candidates → risk-sized orders → PaperBroker → orders/positions
08:15 UTC  update_portfolio_nav    mark-to-market snapshot → portfolio_nav
```

Ingestion jobs (06:xx) run **strictly sequential** — each commits before the next starts. Analysis is the join point. Trades depend on analysis; NAV depends on trades. A 45-minute gap before `run_analysis` absorbs ingestion overruns.

| Job | Inputs | External calls | DB writes (upsert) | Success criterion |
|---|---|---|---|---|
| `fetch_macro_data` | FRED API key, series config | FRED REST (13 series) | `macro_series (series_id, ts)` + `release_ts` | ≥1 series updated OR all current; no write error |
| `fetch_news_sentiment` | watchlist symbols, Finnhub key | Finnhub `/company-news`, CBOE CSV, EDGAR EFTS | `news_sentiment`, `market_sentiment`, `sec_filings (accession_no)`, `insider_transactions (accession_no, txn_seq)` | each sub-source independently succeeds or marks-missing; no abort |
| `fetch_market_data` | watchlist + intermarket ticker list | yfinance (Twelve Data fallback) | `market_bars (symbol, ts)` | every symbol has a bar for last trading day OR explicitly logged missing |
| `fetch_fundamentals` | watchlist symbols | yfinance financials, earnings dates; FINRA on publish days | `fundamentals_quarterly`, `earnings_calendar`, `earnings_estimates`, `analyst_estimates`, `short_interest` | upsert-on-change; no error (stale-but-present is success) |
| `run_analysis` | all DB tables above, `config/strategy.yaml` | **none** | `signal_values (symbol, ts, signal_id)` + `data_completeness` | composite score written for every watchlist symbol with ≥1 available category |
| `execute_paper_trades` | `signal_values`, `config`, current positions | **none** (PaperBroker is in-process) | `orders`, `positions` (via PortfolioManager→BrokerAdapter) | every intended order reaches a terminal state (FILLED/REJECTED); ledger balances |
| `update_portfolio_nav` | `positions`, latest `market_bars` close | **none** | `portfolio_nav (ts)` | one NAV row for the day; equity = cash + Σ(qty×price) |

> Trading-table names (`orders`, `positions`, `portfolio_nav`) are referenced as the expected schema owned by Database Optimizer / Backend Architect — flagged in handoff, not invented here.

---

## 2 — Failure modes and recovery

Design principle: **ingestion failures degrade, they never abort.** A missing source becomes a missing signal, which §3.3 of synthesis renormalizes around. Only `execute_paper_trades` failures roll back.

### 2.1 `fetch_market_data`

```
yfinance call
 ├─ ok, non-empty frame ────────────────► upsert market_bars
 ├─ rate-limited / empty frame / timeout ─► retry (3×, expo backoff 5/15/45s)
 │                                          └─ still failing ─► Twelve Data fallback (same Protocol)
 │                                                               ├─ ok ─► upsert market_bars
 │                                                               └─ fail ─► per-symbol: log missing, continue
 └─ partial (some symbols empty) ─────────► fetch good ones, mark empties missing, do NOT abort batch
```
- **Both providers fail for a symbol** → that symbol simply lacks a fresh bar; `run_analysis` scores it on prior bars / lowers `data_completeness`.
- **Both fail for the entire universe** (network down) → no fresh bars at all → `run_analysis` detects "no bar for last trading day across universe" → **skip trading for the day, log `DATA_BLACKOUT`**, hold portfolio. NAV still snapshots on last-known prices.

### 2.2 `fetch_news_sentiment` / `fetch_fundamentals`
- **Finnhub quota exhausted** → degrade (RSS or skip), mark `news_sentiment` missing → sentiment overlay defaults to 0 (synth §3.3). Never an abort.
- **EDGAR 403** → almost always the missing `User-Agent: name email` header; retry once with header asserted, else mark filings missing for the day (event tags = +0).
- **FINRA file not yet published** → use cached `short_interest`; bi-monthly cadence means staleness is expected and acceptable.
- **FRED series unrevised/stale** → carry last value forward (series legitimately don't update daily); not a failure.
- **yfinance fundamentals empty** (e.g. BRK-B, PLD coverage gaps) → expected; renormalize per synth §3.3.

### 2.3 `run_analysis`
```
read DB
 ├─ ≥1 category present for a symbol ─► score on available, record data_completeness
 ├─ a whole category missing ─────────► category floor (synth §3.3), flag low coverage
 ├─ ZERO usable data universe-wide ───► produce NO signals → log NO_SIGNALS, portfolio holds
 └─ config invalid (pydantic) ────────► FATAL: abort run, alert, do NOT trade on bad config
```
A single provider's failure must **not** abort analysis — it scores on what's in the DB. The only fatal path is invalid `strategy.yaml` (we refuse to trade on an unvalidated config).

### 2.4 `execute_paper_trades`
```
for each intended order (in a single DB transaction):
   PortfolioManager → BrokerAdapter.place_order → PaperBroker
 ├─ all orders succeed ───► COMMIT (orders + positions + cash ledger atomically)
 ├─ any DB write fails ───► ROLLBACK entire batch → log → retry idempotently next misfire window
 └─ risk check rejects ───► order → REJECTED (terminal), logged, others continue
```
- **Crash mid-batch** → the open transaction never commits → on restart, idempotency (deterministic order keys for the date) prevents double-fills. Either the whole batch applied or none did.
- **Analysis produced no signals** → no orders generated → portfolio holds, log `NO_TRADES (reason)`.

### 2.5 Market-closed detection (weekends + holidays)
A guard runs at the **head of `fetch_market_data` and `run_analysis`**:
```
is_trading_day(today)?
 ├─ weekend ───────────► skip all jobs, log MARKET_CLOSED
 ├─ exchange holiday ──► skip, log MARKET_CLOSED (calendar via pandas-market-calendars / config)
 ├─ early close ───────► run normally (daily bars unaffected)
 └─ open ──────────────► proceed
```
Secondary signal: if `fetch_market_data` returns no *new* trading day vs the last stored bar date, treat as closed and skip downstream trading even if the calendar check was unavailable.

---

## 3 — Data flow diagram (one symbol, end to end)

Tracing **AAPL** from API to dashboard:

```
yfinance Ticker.history("AAPL")                         [fetch_market_data 06:30]
   │  raw provider DataFrame (Open/High/Low/Close/Volume, tz-aware)
   ▼
normalize → OHLCVBar(symbol=AAPL, ts, o,h,l,c,v, adj_close)
   │  validation: monotonic ts, no negatives, dedupe
   ▼
UPSERT market_bars (AAPL, ts)                            [idempotent, natural key]
   │
   ├──────── parallel context already in DB ────────────┐
   │  macro_series (regime), news_sentiment(AAPL),       │
   │  fundamentals_quarterly(AAPL), earnings_calendar    │
   ▼                                                     ▼
run_analysis reads AAPL slice + universe                 [07:30, DB-only]
   │  1. per-symbol regime classify → {momentum|reversion}
   │  2. technical sub-score (blended momentum, trend gate, ATR, RSI/BB…)
   │  3. fundamental sub-score (earnings accel, quality, valuation tilt)
   │  4. base = tech·w_tech + fund·w_fund
   │  5. + bounded sentiment overlay  + event tags (PEAD/insider/8-K)
   │  6. × macro multiplier × sector tilt × calendar size factor
   ▼
final_score(AAPL) + data_completeness                    → UPSERT signal_values (AAPL, ts, …)
   │
   ▼
SymbolRanker: AAPL ranked vs 50-universe                 [execute_paper_trades 08:00]
   │  above buy cutoff?  size = ATR risk-parity (risk_manager)
   ▼
order decision → PortfolioManager → BrokerAdapter.place_order
   │  PaperBroker fills at next-open/close model
   ▼
orders(AAPL, PENDING→FILLED) + positions(AAPL qty)       [atomic txn]
   │
   ▼
update_portfolio_nav: AAPL position marked to close      [08:15]  → portfolio_nav
   │
   ▼
FastAPI /portfolio /market /algorithms reads DB          → SvelteKit dashboard
   (NAV chart · candlestick · trades table · signal breakdown for AAPL)
```

Every arrow is a DB boundary or an in-process call — **no service-to-service RPC** (CLAUDE.md: services talk only through the DB).

---

## 4 — State machine for trade orders

```
            place_order
   (none) ───────────────► PENDING
                              │
            ┌─────────────────┼──────────────────┐
   risk/broker reject     fill model           cancel (config/guard)
            │                 │                    │
            ▼                 ▼                    ▼
         REJECTED          FILLED              CANCELLED
        (terminal)      (terminal)            (terminal)
                              │
                     partial fill model?
                              ▼
                      PARTIALLY_FILLED ──► FILLED  (remainder fills)
                                       └──► CANCELLED (remainder pulled, EOD)
```

| State | Meaning | Valid transitions |
|---|---|---|
| `PENDING` | created, not yet executed by broker | → `FILLED`, `PARTIALLY_FILLED`, `REJECTED`, `CANCELLED` |
| `PARTIALLY_FILLED` | some qty executed (only if PaperBroker models partials) | → `FILLED`, `CANCELLED` |
| `FILLED` | fully executed, position + cash updated | terminal |
| `REJECTED` | risk_manager or broker refused (insufficient cash, sizing rule) | terminal |
| `CANCELLED` | pulled before fill (guard, market-closed, day rollover) | terminal |

Rules: every order **must reach a terminal state within the day** (a `PENDING` order at NAV time is a bug → force `CANCELLED`, log). Phase-1 PaperBroker default is the simple `PENDING→FILLED` path; `PARTIALLY_FILLED` is a modeled option, not required. Idempotency: replaying `execute_paper_trades` with the same date/decision set must not move an already-terminal order.

---

## 5 — Scheduler recovery behavior (Pi reboot)

APScheduler + PostgreSQL job store means missed runs are evaluated against `misfire_grace_time=3600` on startup. `coalesce=True` collapses multiple missed firings into one.

| Reboot window | On startup, scheduler does |
|---|---|
| **Before 06:00** | Nothing missed; normal schedule resumes. |
| **Mid-ingestion (06:00–07:30)** | Missed ingestion jobs within grace (≤1h) → run once (coalesced), in sequence. Each is idempotent → safe. Past-grace jobs → skip, log `MISFIRE_SKIP`; `run_analysis` proceeds on whatever data landed (degraded `data_completeness`). |
| **Between analysis and trades (07:30–08:00)** | If `run_analysis` committed `signal_values` for today → `execute_paper_trades` fires within grace, reads existing signals, idempotent. If analysis didn't complete → rerun analysis (DB-only, fast) then trade. |
| **Mid-trade-execution** | Open txn rolled back by Postgres on crash → no partial fills. On restart, idempotent replay either re-executes the full batch or no-ops if it had committed. |
| **After 08:15 (all done)** | Today's jobs already committed; nothing reruns (idempotent keys + coalesce). Next firing is tomorrow. |
| **Past grace entirely (Pi off all day)** | All of today's jobs `MISFIRE_SKIP`. **No catch-up trading on stale data.** Log a gap; resume cleanly next trading day. |

Guiding rule: **never trade on data fetched outside today's intended window.** A long outage skips the day rather than acting late on stale prices.

---

## 6 — Monitoring hooks (structured JSON logs)

Every job emits structured logs the dashboard reads for a system-health panel. One log line = one JSON object; no free-text-only logs.

**Per-job lifecycle event:**
```json
{
  "ts": "2026-05-28T06:30:04Z",
  "level": "INFO",
  "job": "fetch_market_data",
  "event": "job_complete",
  "run_id": "2026-05-28T06:30:00Z",
  "status": "success",            // success | degraded | skipped | failed
  "duration_ms": 41280,
  "symbols_requested": 66,
  "symbols_ok": 64,
  "symbols_missing": ["NEM", "PLD"],
  "provider": "yfinance",         // or "twelve_data" on fallback
  "fallback_used": false
}
```

**Required events per stage:**

| Job | Key logged fields / events |
|---|---|
| all | `job_start`, `job_complete`, `status`, `duration_ms`, `run_id` |
| `fetch_*` | source, `fallback_used`, rows upserted, `symbols_missing`, retry count, rate-limit hits |
| `run_analysis` | symbols scored, mean/median `data_completeness`, macro regime + multiplier, `NO_SIGNALS` flag, profile counts (momentum vs reversion) |
| `execute_paper_trades` | orders by terminal state (filled/rejected/cancelled), cash before/after, rejects with reason |
| `update_portfolio_nav` | NAV value, daily Δ, cash, position count |
| scheduler | `MISFIRE_SKIP`, `MARKET_CLOSED`, `DATA_BLACKOUT`, reboot-recovery decisions |

**System-health derivation for the dashboard:** last successful run per job, current/last regime, today's `data_completeness`, and a red/amber/green per job from `status`. Status semantics: `degraded` = ran but some sources missing (amber); `skipped`/`failed` distinguish "intentionally didn't run" from "tried and broke."

---

## Handoff notes

**What this produced:** the full daily job DAG (canonical CLAUDE.md times + synthesis fan-out), per-job I/O and success criteria, a complete failure/recovery tree for all six jobs, the single-symbol end-to-end data flow, the order-state machine, reboot-recovery behavior keyed to `misfire_grace_time`, and a structured-JSON logging contract for the health dashboard.

**For Backend Architect:**
- Implement the two job classes literally: ingestion (06:xx, external calls, per-source try/degrade) vs compute (07:30+, DB-only, no network). `run_analysis` must not be able to call a provider.
- APScheduler config is load-bearing: PostgreSQL job store, `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1` per job. Reboot recovery (§5) depends on all four.
- `execute_paper_trades` wraps the order batch in **one** DB transaction; PortfolioManager → BrokerAdapter only (never a broker directly). Force-cancel any `PENDING` order surviving to NAV time.
- Idempotency keys must exist before this works: bars `(symbol,ts)`, filings `(accession_no)`, signals `(symbol,ts,signal_id)`, and a deterministic per-date order key so replay can't double-fill.
- Order-state enum (§4) and the `status` enum for job logs (§6) should be shared types.

**For DevOps Automator:**
- Scheduler container needs the PostgreSQL job store reachable at boot and an ordered startup dependency on `db` (health-check gate) so the job store loads cleanly after a Pi reboot.
- Log transport: jobs emit JSON to stdout → Docker captures → dashboard reads. No separate log shipper required Phase 1; ensure stdout isn't buffered away (`PYTHONUNBUFFERED=1`).
- A full-day outage must resume cleanly next trading day (§5) — verify the job store doesn't fire a storm of past-grace catch-ups on reboot (`coalesce` + grace must be set, else Reality Checker's clean-start gate fails).
- Health endpoint: surface last-successful-run-per-job from the structured logs / a `job_runs` table so `docker`-level and app-level health agree.

**Open questions deferred:**
- Exact trading tables (`orders`, `positions`, `portfolio_nav`, optional `job_runs`) are **owned by Database Optimizer / Backend Architect** — I referenced expected shapes but did not define columns. Confirm `job_runs` exists (or logs-only) for the health panel.
- Fill model in PaperBroker (next-open vs same-close, partial fills) is a Backend Architect decision; the state machine supports either.
- `pandas-market-calendars` vs a static holiday config for §2.5 — pick one; either satisfies the closed-market guard.
