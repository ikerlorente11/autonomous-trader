<!-- Agent: Analytics Reporter | Phase: 6 | Depends on: docs/finance/performance-metrics.md, docs/finance/reporting-structure.md, docs/design/ux-architecture.md, backend/api/routers/, frontend/src/routes/ -->

# Phase 6 — Analytics Layer Validation

Validates that every metric defined by the Financial Analyst (`performance-metrics.md`)
and FP&A Analyst (`reporting-structure.md`) is **computed correctly, exposed by an
endpoint, and displayed in the dashboard** — and traces each data type from source to
screen to find gaps.

**Verdict: the core return/risk/trade metrics are computed correctly and reach the UI,
but the analytics layer has three blocker-class gaps:** (1) the benchmark series is
never populated, so alpha/beta/SPY-overlay are permanently dead; (2) `nan`/`inf` metric
values are serialized into the performance response and will almost certainly break that
endpoint at runtime; (3) the FP&A reporting layer (period-over-period, P&L attribution,
signal-quality view) is largely unimplemented.

Legend: ✓ done · ✗ missing · ◑ partial.

---

## 1 — KPI COMPLETENESS AUDIT

Each metric checked across four columns: **Computed** (`backend/analysis/performance/metrics.py`),
**Exposed** (a FastAPI endpoint actually returns it), **Displayed** (a frontend route
renders it), **Formula** (math verified against the source-doc definition).

### 1.1 Portfolio performance metrics (Financial Analyst §1)

| Metric | Computed | Exposed | Displayed | Formula | Notes |
|---|---|---|---|---|---|
| Total Return | ✓ `total_return` | ✓ `returns.total` | ✓ /portfolio | ✓ | `end/start − 1`; abs+pct. Correct. |
| CAGR | ✓ `cagr` | ✓ `returns.annualized` | ✓ /portfolio | ✓ | calendar years / 365.25; guards `start<=0`. Correct. |
| Sharpe | ✓ `sharpe_ratio` | ✓ `risk.sharpe` | ✓ / + /portfolio | ✓ | `mean(excess)/std(ddof=1)·√252`. Correct. **Does NOT need benchmark** (NAV-only) — see §4.3. |
| Sortino | ✓ `sortino_ratio` | ✓ `risk.sortino` | ✓ /portfolio | ✓ | downside dev = RMS of `min(excess,0)` over **all** periods (MAR=rf). Matches doc §1 note. |
| Max Drawdown | ✓ `max_drawdown` | ✓ `risk.max_drawdown` | ✓ / + /portfolio | ✓ | `min(NAV/cummax − 1)`; peak/trough/recovery + day counts. `recovery_ts=None` when underwater. Correct. |
| Calmar | ✓ `calmar_ratio` | ✓ `risk.calmar` | ✓ /portfolio | ✓ | `CAGR/|mdd|`. Correct. |
| Win Rate | ✓ `win_rate` | ✓ `trades.win_rate` | ✓ / + /portfolio | ✓ | `count(pnl>0)/count`. Correct. |
| Profit Factor | ✓ `profit_factor` | ✓ `trades.profit_factor` | ✓ /portfolio | ✓ | `gross_profit/gross_loss`; `inf` if no losses. Correct — but `inf` **breaks JSON serialization**, see §4. |
| Avg Win / Avg Loss / ratio | ✓ `avg_win_loss` | ✓ `trades.avg_win/avg_loss/win_loss_ratio` | ✓ /portfolio | ✓ | Correct. |
| Alpha / Beta vs SPY | ✓ `alpha_beta` | ✓ `returns.alpha/beta` | ✓ /portfolio | ✓ (math) | Jensen's α annualized, β=cov/var(ddof=1). Math correct **but input is always empty** — benchmark never populated (§1.4, §4.3). Always `nan`. |
| Benchmark return | ✓ via `total_return(…, "benchmark_value")` | ✓ `returns.benchmark` | ✓ /portfolio | ✓ | Same: always `nan` — no data. |

### 1.2 Signal-quality metrics (Financial Analyst §2)

| Metric | Computed | Exposed | Displayed | Formula | Notes |
|---|---|---|---|---|---|
| Signal accuracy | ✓ `signal_accuracy` | ✗ | ✗ | ✓ | Function correct, but **no endpoint calls it and no UI renders it**. Also has no data — see §1.4. |
| Hit rate by sector | ✓ `signal_hit_rate_by_sector` | ✗ | ✗ | ✓ | Same — orphaned function. |
| Holding-period profitability | ✓ `avg_holding_period_profitability` | ✗ | ✗ | ✓ | Same — orphaned function. `summarize_performance` does not bundle any §2 metric. |

> **The entire signal-quality layer is computed but unwired.** `summarize_performance`
> (the only thing `/portfolio/performance` calls) returns only `returns`/`risk`/`trades`.
> The three §2 functions are dead code from the API's perspective. The UX/Financial-Analyst
> handoffs both asked for a "Signal quality view" (overall accuracy, hit-rate-by-sector
> bar, holding-period table, with sample size shown) — **none of it exists in the UI.**

### 1.3 FP&A dashboard cards (reporting-structure §4) — the nine-card spec

| # | Card | Computed | Exposed | Displayed | Notes |
|---|---|---|---|---|---|
| 1 | Portfolio Value (NAV) + daily Δ% | ✓ | ✓ summary + nav | ✓ / (hero) | Daily Δ derived client-side from last two NAV rows (no intraday feed — acceptable). |
| 2 | Today's P&L ($ and %) | ✓ | ✓ | ✓ / (hero) | Same source as Card 1. |
| 3 | Total Return | ✓ | ✓ | ✓ / (Total P&L) + /portfolio | OK. |
| 4 | **Alpha vs SPY (MTD)** | ◑ | ◑ | ✗ as a card | α computed but always `nan` (no benchmark); no MTD period. **Not built.** |
| 5 | Max Drawdown | ✓ | ✓ | ✓ / + /portfolio | OK. |
| 6 | Sharpe (rolling 90d) | ✓ | ✓ | ✓ / | Labeled "Sharpe (90d)" but computed over the full `/performance` window (default 365d), **not** 90d. Minor mislabel. |
| 7 | **Cash / Exposure** | ◑ | ✓ cash in summary | ◑ | Cash shown as a card on /portfolio; **no exposure % and no exposure-over-time**; not on dashboard. |
| 8 | **Market Regime** | ✗ | ✗ | ✗ | No regime anywhere (macro signals not built per CLAUDE.md status note). Status-palette chip absent. |
| 9 | Simulation Health | ✓ | ✓ /system/status | ✓ header dot + banner | Health rollup from `job_runs` only (see §2, §4.5). Status palette correctly separated from money palette. |

**Two-palette rule (load-bearing UX rule):** ✓ enforced — `tokens.css` separates
`--pnl-*` from `--status-*`; health dot/banner use status palette only. Good.

### 1.4 Why "Computed ✓ / no data" happens for several metrics

Two unimplemented producers leave correctly-built consumers permanently empty:

- **`benchmark_value` is never written.** `PortfolioManager.snapshot_nav`
  ([portfolio_manager.py:91](../../backend/trading/portfolio_manager.py#L91)) inserts
  only `cash`/`equity`/`total`. The column exists (schema + API + chart all read it),
  but nothing populates it from SPY closes in `market_bars` as `performance-metrics.md §9`
  specifies. ⇒ `benchmark`, `alpha`, `beta` are always `nan`; the NavChart SPY overlay
  never renders (`hasBenchmark` is always false). **Blocker.**
- **No signal "settle" job exists.** `algorithm_signals.realized_return`/`outcome`
  columns exist, but `scheduler/jobs.py` ships only the 4 jobs (`fetch_market_data`,
  `run_analysis`, `execute_paper_trades`, `update_portfolio_nav`) — none backfills
  forward returns. ⇒ `signal_accuracy`/`hit_rate_by_sector` always `nan`. The Financial
  Analyst flagged this as "expected, not a bug" until the settle job lands — confirmed
  still missing.

> **Resolved open question:** `performance-metrics.md` flagged a possible column-name
> mismatch (`benchmark` vs `benchmark_value`). The schema, ORM model, API, and
> `metrics.py` default all now use **`benchmark_value`** consistently — no mismatch. The
> remaining problem is population, not naming.

---

## 2 — DATA FLOW VERIFICATION

| Trace | source → table → endpoint → UI | Status |
|---|---|---|
| **Market bar** | yfinance → `market_bars` → `GET /api/market/bars/{symbol}` → candlestick (`/market/[symbol]`) | ✓ every step present. Endpoint [market.py:22](../../backend/api/routers/market.py#L22); dynamic route exists. |
| **NAV** | `update_portfolio_nav` → `portfolio_nav` → `GET /api/portfolio/nav` → NavChart | ◑ NAV line works end-to-end. **SPY-overlay leg is broken**: `benchmark_value` never written, so the second dataset never appears. |
| **Signal** | `run_analysis` → `algorithm_signals` → `GET /api/algorithms/signals` → signals panel | ✓ end-to-end. Dashboard "Top Signals" + Market watchlist scores both consume it. |

Supporting traces checked:
- **Performance bundle:** `portfolio_nav` + `trade_orders` → `summarize_performance` →
  `GET /api/portfolio/performance` → /portfolio metric groups + dashboard cards. ✓ wired,
  but see §4 (nan/inf serialization) and §1.4 (alpha/beta empty).
- **Trades ledger:** `trade_orders` → `GET /api/trades` → trades tables. ✓ — **but
  `realized_pnl` per closing leg is not surfaced** (TradeRecord has no realized P&L;
  `build_round_trips` computes it server-side only for the aggregate). reporting §5.2
  expects `realized_pnl`/`cost_basis`/`signal_score` columns — not exposed.
- **Health:** `job_runs` → `GET /api/system/status` → header dot + banner + /system. ✓
  for job status; the other five FP&A §3.1 health checks (NAV continuity, bar freshness,
  signal coverage, stuck-PENDING, ledger reconciliation) are **not computed**.

---

## 3 — MISSING METRICS (defined in docs/finance/, not implemented)

### Blockers (a core reporting deliverable is absent)

1. **Benchmark population → alpha/beta/SPY-overlay** (reporting §2.1, perf-metrics §9).
   The single highest-impact gap: Card 4 and a headline value prop ("vs SPY") are dead.
   Fix is small and additive: in `snapshot_nav`, look up the SPY close in `market_bars`
   for `as_of` and write it (or a normalized benchmark NAV) into `benchmark_value`.
2. **`nan`/`inf` serialization** (correctness — see §4.2). Not a "missing metric" but it
   makes the implemented ones unreliable; listed here because it gates the whole endpoint.
3. **Period-over-period reporting** (reporting §1.2, §2.1; UX §3.1 period switcher).
   WTD/MTD/YTD/Inception and rolling 30/60/90 are **not implemented** — no period
   endpoint, no period switcher in the UI. The dashboard computes only a crude "daily"
   delta from the last two NAV points. Every card the UX spec says is "driven by one
   period control" is effectively fixed-window.
4. **P&L attribution** (reporting §1.3, §4). No per-symbol P&L, no per-sector P&L bar, no
   Best/Worst contributors table. These are explicit FP&A deliverables and dashboard
   wireframe items (UX §3.1) — entirely absent.
5. **Signal-quality view** (perf-metrics §2 + handoff). Functions exist; no endpoint, no
   UI (§1.2).

### Nice-to-haves (defined, deferrable)

- **Realized vs unrealized P&L split** in the trade ledger (reporting §1.1, §5.2):
  unrealized is in `/portfolio/summary`; realized-per-trade is not surfaced.
- **Export artifacts** (reporting §5): `nav_history.csv`, `trades.csv`, `summary.json`
  for Experiment Tracker ingestion — not implemented. Deferred until Experiment Tracker
  consumes them.
- **Extended health checks** (reporting §3.1): NAV continuity, bar freshness %, signal
  coverage, stuck-PENDING, ledger reconciliation — only job-status drives health today.
- **Regime/exposure context** (Cards 7–8): blocked on macro signals (out of current scope
  per CLAUDE.md implementation-status note) — not a Phase-6 blocker, but the cards should
  degrade explicitly rather than be silently absent.

---

## 4 — EDGE CASES IN REPORTING

### 4.1 Portfolio has never traded (day 1) — **handled cleanly ✓**
`/portfolio/performance` returns empty `PerformanceMetrics()` when `len(nav_rows) < 2`
([portfolio.py:120](../../backend/api/routers/portfolio.py#L120)) ⇒ all dicts empty ⇒
frontend renders "—" with neutral bands. `summary` shows NAV=starting cash, Total P&L=$0,
0 positions. Trades/signals tables show their empty states. No crash, no misleading
numbers. **This is the one path with no nan/inf, so it is also the only path that safely
avoids the §4.2 bug.**

### 4.2 nan/inf in the performance response — **likely runtime blocker ✗ (verify)**
Once there are ≥2 NAV rows, `summarize_performance` emits real `nan`/`inf` floats:
`alpha`/`beta`/`benchmark` are `nan` (no benchmark data, steady state), `profit_factor`
is `inf` when there are wins but no losses, and Sharpe/Sortino/Calmar are `nan` for
degenerate windows. The API uses the **default** response class (no ORJSON, no sanitizer
— [main.py:25](../../backend/api/main.py#L25)). Starlette's `JSONResponse` serializes with
`allow_nan=False`, which **raises `ValueError` on nan/inf → HTTP 500** (and if any layer
instead used `allow_nan=True`, it would emit the `NaN`/`Infinity` tokens that
`JSON.parse` rejects). Either way, `/portfolio/performance` is expected to fail for the
normal post-day-1 state. **Must be verified at runtime**; if confirmed, sanitize
nan/inf → `null` at the API boundary (e.g. map non-finite floats to `None` before
returning, or use a custom encoder). The frontend already treats `null` as "—".

### 4.3 All positions at a loss — **handled correctly ✓**
Negative `total_pnl`/`unrealized_pnl`/Total Return render red via the P&L palette;
`max_drawdown` lands in the red band. Nothing breaks. Critically, because money and health
use separate palettes, a red P&L does **not** trip the health chip — correct per FP&A §3.1
(a losing strategy ≠ a broken sim).

### 4.4 Benchmark unavailable (premise: "Sharpe needs benchmark") — **premise corrected ◑**
Sharpe/Sortino/Calmar/Max-DD are **NAV-only** and keep working without a benchmark — only
`alpha`/`beta`/`benchmark` depend on it, and `alpha_beta` degrades to `nan,nan` when the
benchmark series has <2 aligned points (no crash). The real issue is that this is not a
transient outage but the **permanent state** (§1.4), and the resulting `nan` triggers the
§4.2 serialization bug. So "benchmark unavailable" is today's default, not an edge case.

### 4.5 Experiment / window with <30 days of data — **no significance guard ✗**
`performance-metrics.md §4` defines the health rule as needing "≥~30 closed trips and
≥~3 months of NAV," but **nothing enforces or surfaces sample size.** Metrics return `nan`
only for `<2` points — a 3-day-old run shows a fully-colored Sharpe with no "insufficient
data" caveat, and `signal_accuracy` carries a `signal_count` that the UI never displays.
Add a sample-size affordance (e.g. dim/"n too small" badge below the FP&A thresholds) so
early, statistically meaningless numbers aren't read as signal.

### 4.6 Health not-OK but cards still show numbers — **load-bearing UX rule only half-met ◑**
UX §4 / FP&A §3.1 require performance cards to show a "data suspect" state when health is
not-OK. Implemented: a non-dismissible banner appears when health is `broken`
([+layout.svelte:95](../../frontend/src/routes/+layout.svelte#L95)). Missing: the
performance **cards themselves do not dim or badge** — they keep rendering numbers
alongside the banner. Partial compliance.

---

## Handoff notes — for Security Engineer

**What I produced:** this checklist — KPI completeness matrix (computed/exposed/displayed/
formula), source-to-screen data-flow traces, a missing-metrics list split into blockers vs
nice-to-haves, and six reporting edge-case assessments.

**Gaps found (analytics-layer; ranked):**
1. **BLOCKER — `benchmark_value` never populated.** `snapshot_nav` writes no benchmark ⇒
   alpha/beta/benchmark always `nan`, SPY overlay never renders, Card 4 dead.
2. **BLOCKER (verify at runtime) — nan/inf serialization.** Default response class +
   Starlette `allow_nan=False` ⇒ `/portfolio/performance` likely 500s for the normal
   post-day-1 state (alpha/beta `nan`, `profit_factor` `inf`). Sanitize non-finite floats
   to `null` at the API boundary.
3. **BLOCKER — FP&A reporting layer largely unimplemented:** no period-over-period
   (WTD/MTD/YTD/Inception/rolling) and no period switcher; no per-symbol/per-sector P&L
   attribution or contributors table.
4. **Signal-quality metrics orphaned:** `signal_accuracy`/`hit_rate_by_sector`/
   `holding_period_profitability` computed but unwired (no endpoint, no UI); also no
   settle job feeds them data.
5. **Partial:** Cards 6 mislabeled "90d" (uses full window); Card 7 no exposure %; Card 8
   regime absent; health uses only job-status (5 other §3.1 checks missing); cards don't
   show a "data suspect" state when health is not-OK; no sample-size/significance guard;
   realized-P&L-per-trade not surfaced; export artifacts absent.

**Security-relevant observations to verify in your audit (flagged, not assessed):**
- **Non-finite-float → 500** (§4.2) is also a robustness/availability concern: an
  unhandled `ValueError` reaching the client may leak a stack trace depending on FastAPI
  debug settings — confirm `debug=False` in production and that the global handler returns
  a generic 500 body. ([main.py:25](../../backend/api/main.py#L25))
- **No auth on any router** — single-user by design (CLAUDE.md), so expected; confirm the
  service is not bound to a public interface and CORS is not wildcard-open.
- **Query-param windows** (`start`/`end`, `symbol`, `limit`) are typed via FastAPI and
  reach the DB through the SQLAlchemy query layer (parameterized) — spot-check the
  `market_queries`/`portfolio_queries` for any string-interpolated SQL while you're there.
- **No real secrets needed by the analytics path** (NAV/metrics are DB-only); the only
  external key surface is data ingestion, outside this layer.
