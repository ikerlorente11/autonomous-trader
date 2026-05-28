<!-- Agent: FP&A Analyst | Phase: 2 | Depends on: docs/research/00-signal-synthesis.md, docs/architecture/workflow-tree.md, docs/finance/performance-metrics.md (Financial Analyst — pending) -->

# Phase 2 — Reporting & P&L Structure

Defines how the paper-trading simulation reports profit & loss, compares performance across time, distinguishes a *broken simulation* from a *bad strategy*, and what the dashboard surfaces. The risk/return statistics themselves (Sharpe, max drawdown, CAGR, alpha vs benchmark, Calmar) are **owned by the Financial Analyst** (`performance-metrics.md`); this document consumes those definitions and specifies the *reporting layer* around them — periodization, attribution, queries, cards, and export.

> **Source-of-truth principle:** every number on the dashboard traces to a row in the database written by a scheduler job. Nothing is computed client-side beyond formatting. The canonical ledger is the trio `orders` → `positions` → `portfolio_nav` produced by `execute_paper_trades` and `update_portfolio_nav` (Workflow Architect). Table names are owned by Database Optimizer / Backend Architect; columns referenced below are the **expected shape** flagged for confirmation.

---

## SECTION 1 — SIMULATION P&L STRUCTURE

### 1.1 The two P&L components

| Component | Definition | Source | When it changes |
|---|---|---|---|
| **Realized P&L** | Proceeds − cost basis on *closed* lots | `orders` (sells matched to buys) | On every closing fill |
| **Unrealized P&L** | (mark price − avg cost) × open qty | `positions` × latest `market_bars` close | Every `update_portfolio_nav` (08:15 UTC) |
| **Total P&L** | Realized + Unrealized | derived | Daily |

- **Lot accounting: FIFO.** Cost basis tracked per opening lot; a sell consumes oldest lots first. Realized P&L is locked at the matched cost. Phase 1 PaperBroker has no commissions/slippage by default, but the cost-basis field must support them so the model is real-broker-ready (BrokerAdapter seam).
- **Mark-to-market price = the daily close** from `market_bars` for the symbol on the NAV date. If no fresh bar (`DATA_BLACKOUT`, workflow §), mark on last-known close and flag the NAV row `stale_marks=true` — never drop the position.
- **NAV is authoritative for return measurement.** Because this is a closed sim with a single initial funding event and no external cash flows after, `daily P&L = NAV_t − NAV_{t-1}`. This time-weighted NAV series — not the order-by-order sum — is what feeds all return metrics, avoiding double-counting between realized and unrealized.

### 1.2 P&L periodization

All periods derive from the `portfolio_nav` daily series. A period's P&L = `NAV_end − NAV_start`; its return = `NAV_end / NAV_start − 1`.

| Period | Window | Definition |
|---|---|---|
| Daily | last completed trading day | `NAV_t − NAV_{t-1}` |
| WTD | Monday → now | vs last Friday's close NAV |
| MTD | 1st of month → now | vs prior month-end NAV |
| YTD | Jan 1 → now | vs prior year-end NAV (or inception if first year) |
| Inception | funding date → now | vs initial capital |

### 1.3 P&L attribution

Two attribution axes, both reusing the ledger + watchlist:

- **Per-symbol P&L** = realized (FIFO-matched closed lots for the symbol) + unrealized (open position mark). Ranked best/worst contributors per period.
- **Per-sector P&L** = Σ per-symbol P&L grouped by `watchlist.sector` (sectors per synthesis §5 — 11 GICS sectors). Sector is joined at read time, so re-sectoring a symbol does not require ledger rewrites.
- **Contribution, not just level:** report each symbol/sector's share of total period P&L (contribution %) so a +$200 winner in a +$1,000 day reads as "20% of the day," matching how the dashboard tells the story.

> **Attribution caveat:** symbol/sector P&L attributes *outcomes*, not *signal credit*. Which strategy version produced the trade is the Experiment Tracker's `strategy_version` linkage (separate concern). FP&A reports money; the Experiment Tracker reports algorithm credit.

---

## SECTION 2 — PERIOD-OVER-PERIOD REPORTING

### 2.1 Comparison set

| Comparison | Numerator | Baseline |
|---|---|---|
| This week vs last week | WTD return | prior full week return |
| This month vs benchmark | MTD return | SPY MTD return (benchmark, synthesis §5) |
| Rolling 30 / 60 / 90 day | trailing-N return & vol | self (trend) and SPY (alpha) |
| Portfolio vs benchmark | period return | SPY same period |

Benchmark return uses SPY closes from `market_bars` over the identical window — same source, no external benchmark feed needed.

### 2.2 Efficient TimescaleDB pre-computation

`portfolio_nav` is one row/day (~252/yr) — tiny. Period math is cheap, but the patterns below keep the API thin and consistent.

**Daily return series (window function over the hypertable):**

```sql
SELECT ts,
       nav,
       nav - LAG(nav) OVER (ORDER BY ts)                       AS daily_pnl,
       nav / NULLIF(LAG(nav) OVER (ORDER BY ts), 0) - 1        AS daily_return
FROM portfolio_nav
ORDER BY ts;
```

**Rolling 30/60/90-day return (anchored to first NAV in the window):**

```sql
SELECT ts,
       nav / NULLIF(FIRST(nav, ts) OVER (
             ORDER BY ts RANGE BETWEEN '90 days' PRECEDING AND CURRENT ROW), 0) - 1
         AS ret_90d
FROM portfolio_nav;
```

**Period buckets for week/month tiles (`time_bucket`):**

```sql
SELECT time_bucket('1 week', ts) AS wk,
       FIRST(nav, ts)            AS nav_open,
       LAST(nav, ts)             AS nav_close,
       LAST(nav, ts) / NULLIF(FIRST(nav, ts), 0) - 1 AS week_return
FROM portfolio_nav
GROUP BY wk ORDER BY wk;
```

**Continuous aggregate (optional, recommended for the NAV chart at multi-year scale):** a `portfolio_nav_daily` CAGG is overkill at 252 rows/yr, but a `portfolio_nav_monthly` rollup (month-open/close/min/max NAV) is worth materializing for the period tiles and YoY views — the synthesis (§6 DB Optimizer) already flagged CAGGs as useful-not-required for NAV rollups. Keep it as a Phase-1.5 optimization, not a blocker.

> **Decision:** Phase 1 computes periods on-the-fly with the window queries above. Materialize the monthly CAGG only if the dashboard's period endpoint exceeds its latency budget — at these row counts it will not.

---

## SECTION 3 — SIMULATION HEALTH INDICATORS

The critical distinction the brief demands: **a broken pipeline and a losing strategy look different in the data.** Health indicators answer *"is the machine running?"*; performance metrics answer *"is the strategy good?"* Never conflate a red P&L (possibly correct behavior in RISK_OFF) with a broken sim.

### 3.1 Health (is the simulation running correctly?)

| Indicator | Healthy | Broken signal | Source |
|---|---|---|---|
| **Job freshness** | all 7 daily jobs ran today, terminal=success | any job missing/failed past `misfire_grace_time` | `job_runs` (or structured logs — confirm with Workflow Architect) |
| **NAV continuity** | exactly one `portfolio_nav` row per trading day | gap on a trading day | `portfolio_nav` |
| **Bar freshness** | latest `market_bars` date = last trading day for ≥90% of universe | universe-wide stale → `DATA_BLACKOUT` | `market_bars` |
| **Signal coverage** | `signal_values` written for the watchlist; mean `data_completeness` ≥ baseline | sudden drop in symbols scored or completeness | `signal_values` |
| **Order terminality** | zero `PENDING` orders at/after NAV time | a stuck `PENDING` = bug (force-cancel + log, workflow §) | `orders` |
| **Ledger balance** | cash + Σ(qty×price) reconciles to NAV | mismatch = accounting bug | `positions`, `portfolio_nav` |

If any health indicator is red, **performance numbers are suspect and the dashboard must say so** (a banner, not a silent stale chart).

### 3.2 Strategy quality (is the algorithm good?) — separate panel

These consume the Financial Analyst metrics and are only trustworthy when §3.1 is all-green:

- Cumulative & period returns vs SPY (alpha)
- Sharpe / Sortino, max drawdown, Calmar (Financial Analyst definitions)
- Win rate, avg win/avg loss, profit factor, hit rate by sector
- Exposure / cash % over time (did the macro multiplier behave? e.g., cash rose in RISK_OFF)

> **Diagnostic pairing:** a flat NAV with all-green health + RISK_OFF regime = the strategy *correctly* sitting in cash, not a break. A flat NAV with a failed `execute_paper_trades` job = a break. The dashboard must let a viewer tell these apart in one glance — this is why §4 puts a regime/health chip next to the return cards.

---

## SECTION 4 — DASHBOARD SUMMARY CARDS

The above-the-fold card row. Each card: one metric, one calculation, a good/bad threshold for color, and an update cadence. Financial color convention per UI Designer (green=gain, red=loss); health cards use a neutral/amber/red status palette, **not** the P&L green/red, so "system OK" never visually reads as "made money."

| # | Card | Metric | Calculation | Good / Bad threshold | Updates |
|---|---|---|---|---|---|
| 1 | **Portfolio Value (NAV)** | latest NAV + daily Δ% | `portfolio_nav` last row; Δ vs prior row | green Δ>0 / red Δ<0 | 08:15 UTC daily |
| 2 | **Today's P&L** | daily P&L $ and % | `NAV_t − NAV_{t-1}` | green / red by sign | daily |
| 3 | **Total Return** | inception return % | `NAV / initial_capital − 1` | green>0 / red<0 | daily |
| 4 | **Alpha vs SPY (MTD)** | portfolio MTD − SPY MTD | both from respective series | green outperform / red underperform | daily |
| 5 | **Max Drawdown** | peak-to-trough % (Financial Analyst def.) | running max of NAV | amber > −10%, red > −20% | daily |
| 6 | **Sharpe (rolling 90d)** | risk-adjusted return (Financial Analyst def.) | from daily-return series | green ≥1, amber 0–1, red <0 | daily |
| 7 | **Cash / Exposure** | cash % of NAV | `cash / NAV` | context (high in RISK_OFF is *correct*) | daily |
| 8 | **Market Regime** | RISK_ON / CAUTION / RISK_OFF | latest regime read (synthesis §4) | status chip (green/amber/red) | daily |
| 9 | **Simulation Health** | all-jobs-green status | §3.1 rollup | green OK / amber degraded / red broken | hourly / per-job |

Cards 1–6 are *performance* (P&L palette). Cards 7–9 are *context/health* (status palette). This split is the single most important UX rule from §3: never let health and money share a color language.

Below the cards: **Best/Worst contributors** (top 5 symbols by period P&L contribution) and **Sector P&L** bar (§1.3).

---

## SECTION 5 — EXPORT FORMAT

For future backtesting comparison and Experiment Tracker ingestion. Three artifacts, CSV (human/Excel) and JSON (machine) for each. Every export carries `strategy_version` so the Experiment Tracker can attribute results to an algorithm version (synthesis §3 / Experiment Tracker dependency).

### 5.1 Daily NAV series — `nav_history.csv`

```
date,nav,cash,positions_value,daily_pnl,daily_return,benchmark_nav,regime,strategy_version,stale_marks
2026-05-27,101240.55,21240.55,80000.00,540.12,0.00536,100890.00,RISK_ON,v1.0.0,false
```

### 5.2 Trade ledger — `trades.csv`

```
order_id,fill_ts,symbol,sector,side,qty,price,cost_basis,realized_pnl,strategy_version,signal_score
A1042,2026-05-27T08:00:12Z,AAPL,Technology,SELL,10,212.40,1980.00,144.00,v1.0.0,78.5
```

(`realized_pnl` populated on closing legs only; opening legs leave it null. `signal_score` = the `final_score` that triggered the order, for signal-vs-outcome analysis.)

### 5.3 Period summary — `summary.json`

```json
{
  "strategy_version": "v1.0.0",
  "period": {"start": "2026-01-01", "end": "2026-05-27"},
  "returns": {"total": 0.0124, "annualized": 0.031, "benchmark": 0.0089, "alpha": 0.0035},
  "risk": {"sharpe": 1.12, "sortino": 1.40, "max_drawdown": -0.067, "calmar": 0.46},
  "activity": {"trades": 84, "win_rate": 0.55, "profit_factor": 1.4, "avg_exposure": 0.78},
  "attribution": {"by_sector": {"Technology": 0.0061, "Energy": -0.0012}},
  "health": {"jobs_complete_pct": 1.0, "mean_data_completeness": 0.91}
}
```

- **Schema is the contract** for the Experiment Tracker comparator: `strategy_version` + `period` + `returns`/`risk`/`activity` keys are the join surface for A/B comparison. The exact `risk` keys mirror the Financial Analyst metric names — keep them identical so no remapping is needed.
- Numbers (Sharpe, drawdown, etc.) are **emitted** here using Financial Analyst formulas; FP&A owns the envelope/format, not the formula.

---

## Handoff notes

**What this document produced:** the simulation P&L model (FIFO realized vs mark-to-market unrealized, NAV-authoritative returns), period-over-period definitions with copy-ready TimescaleDB window/`time_bucket` queries, the health-vs-strategy diagnostic split, the nine dashboard summary cards with thresholds and the two-palette rule, and CSV/JSON export schemas keyed on `strategy_version`.

**For the Frontend Developer — build these:**
- **Card row (9 cards, §4):** Cards 1–6 use the P&L green/red palette; Cards 7–9 use a *separate* status palette (green/amber/red). Do not share color language between money and health — this is the load-bearing UX rule.
- **NAV chart:** time series from `nav_history` with a SPY benchmark overlay; shade regions by `regime` if cheap.
- **Two tables:** (a) Best/Worst contributors (top/bottom 5 by period P&L contribution %); (b) full trades table from the §5.2 ledger shape, sortable, with realized P&L colored.
- **Sector P&L bar** (§1.3) — green/red bars by sector contribution.
- **Health banner:** when §3.1 is not all-green, show a non-dismissible banner; performance cards must visually indicate "data suspect" rather than silently showing stale numbers.
- **Period switcher** (Daily / WTD / MTD / YTD / Inception + rolling 30/60/90) driving all cards, charts, and attribution from one control.

**Open questions / deferred:**
- Confirm `job_runs` table exists vs logs-only for Card 9 (flagged by Workflow Architect too).
- Confirm trading-table column names (`orders`, `positions`, `portfolio_nav`, `cost_basis`) with Database Optimizer / Backend Architect — shapes assumed, not defined here.
- **Blocked on Financial Analyst** (`performance-metrics.md`): exact Sharpe/Sortino/drawdown/Calmar/alpha formulas and the risk-free-rate input. Cards 4–6 and `summary.json` risk keys reference these by name; finalize once that doc lands.
