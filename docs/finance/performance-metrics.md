<!-- Agent: Financial Analyst | Phase: 2 | Depends on: docs/research/00-signal-synthesis.md, docs/architecture/schema.md, docs/architecture/workflow-tree.md -->

# Phase 2 — Performance Measurement Layer

Defines **how the simulation's performance is measured**: the portfolio risk/return statistics, the trade-level quality metrics, the signal-predictiveness metrics, and the thresholds that decide whether the algorithm is actually working. This document is the source of truth for every number that answers *"is the strategy any good?"* — the FP&A reporting layer (`reporting-structure.md`) consumes these definitions; it does not redefine them.

All computation is implemented as **pure functions** in [`backend/analysis/performance/metrics.py`](../../backend/analysis/performance/metrics.py): each accepts a DataFrame (plus scalar config), reads nothing external, writes nothing, and returns typed numeric results. The DB/query layer materializes the DataFrames; this module only does math.

> **Benchmark = SPY** (synthesis §5: SPY is the benchmark / RS denominator / regime anchor). Benchmark returns come from the `benchmark` column of `portfolio_nav`, sourced from SPY closes in `market_bars` over the identical window — no external benchmark feed.

> **Risk-free rate** is read once from the `RISK_FREE_RATE` env var (annual, default **4.5%**) by `risk_free_rate_from_env()` and passed into the metric functions, which stay pure. It is *not* hardcoded inside any metric.

---

## Input shapes

Two DataFrame shapes recur. Column names mirror the schema (Database Optimizer) so no remapping is needed.

| Shape | Source table | Required columns | Used by |
|---|---|---|---|
| **NAV frame** | `portfolio_nav` | `ts` (datetime), `total` (float); optional `benchmark` | all return/risk metrics |
| **Orders frame** | `trade_orders` | `symbol`, `side`, `qty`, `price`, `ts`; optional `status` | `build_round_trips` |
| **Trips frame** | derived | `pnl`; optional `symbol`, `return_pct`, `holding_days` | trade-level + holding-period metrics |
| **Signals frame** | `algorithm_signals` | `action`; `outcome` and/or `realized_return` | signal-quality metrics |

**Why NAV is authoritative:** this is a closed sim with a single funding event and no external cash flows after, so the daily `total` series is time-weighted by construction. All return and risk metrics derive from it — never from the order-by-order P&L sum, which would double-count realized vs unrealized.

---

## 1 — Portfolio performance metrics

| Metric | Function | Definition / formula | Returns |
|---|---|---|---|
| **Total Return** | `total_return(nav)` | abs = `NAV_end − NAV_start`; pct = `NAV_end / NAV_start − 1` | `TotalReturn(absolute, pct)` |
| **CAGR** | `cagr(nav)` | `(NAV_end / NAV_start) ** (1 / years) − 1`, years from calendar span | `float` |
| **Sharpe** | `sharpe_ratio(nav, rf)` | `mean(excess) / std(excess) · √252`, excess = daily return − rf/252 | `float` |
| **Sortino** | `sortino_ratio(nav, rf)` | as Sharpe but denominator = downside deviation (RMS of negative excess only) | `float` |
| **Max Drawdown** | `max_drawdown(nav)` | min of `NAV / running_max − 1`; plus peak/trough/recovery timestamps and day counts | `DrawdownResult` |
| **Calmar** | `calmar_ratio(nav)` | `CAGR / |max_drawdown|` | `float` |
| **Win Rate** | `win_rate(trips)` | `count(pnl > 0) / count(trips)` | `float` |
| **Profit Factor** | `profit_factor(trips)` | `gross_profit / gross_loss` (∞ if no losses and some profit) | `float` |
| **Avg Win / Avg Loss** | `avg_win_loss(trips)` | mean of winning pnl, mean of losing pnl, and their ratio | `WinLossStats` |
| **Alpha / Beta vs SPY** | `alpha_beta(nav, rf)` | OLS of excess portfolio return on excess benchmark return; β = cov/var, annualized Jensen's α = `(mean_excess_p − β·mean_excess_b) · 252` | `AlphaBeta(alpha, beta)` |

**Convention notes**
- **Sample std (`ddof=1`)** throughout — we estimate from a sample, not a population.
- **Sortino downside deviation** uses RMS over *all* periods (negative excess set to 0, then RMS), not only over the negative subset — the standard MAR=rf formulation, so it is comparable to Sharpe.
- **Drawdown is a negative fraction** (e.g. `-0.18`). `recovery_ts`/`recovery_days` are `None` when the drawdown has not yet recovered — the dashboard must render "underwater" rather than blank.
- **Round trips are FIFO, long-only** (`build_round_trips`): a sell consumes the oldest open buy lots first; sell quantity beyond open lots is ignored (no shorting in Phase 1). Open positions produce no trip — trade-level metrics are realized-only by design. Unrealized contribution lives in NAV-based metrics.
- **Degenerate inputs return `nan`** (e.g. <2 NAV points, zero volatility, empty trips) rather than raising — the dashboard renders "—" for `nan`.

---

## 2 — Signal quality metrics

These answer the deeper question: *are the algorithm's signals predictive, independent of position sizing and trade timing?* They read `algorithm_signals`, where a scheduler **settle job** later fills `realized_return` and `outcome` for each signal once its target horizon has elapsed (schema §, workflow §).

| Metric | Function | What it measures |
|---|---|---|
| **Signal accuracy** | `signal_accuracy(signals)` | fraction of *settled actionable* (default `buy`) signals that were correct. Correctness = explicit `outcome` if present, else sign of `realized_return` (>0 ⇒ correct). Unsettled rows excluded. |
| **Hit rate by sector** | `signal_hit_rate_by_sector(signals, sector_map)` | accuracy grouped by `watchlist.sector` — exposes *where* the edge concentrates. `sector_map` is `{symbol: sector}` joined at read time. |
| **Holding-period profitability** | `avg_holding_period_profitability(trips)` | avg return, avg pnl, and win rate bucketed by holding days (default bins `0-5 / 5-10 / 10-20 / 20-60 / >60d`). Validates whether the 1–4 week target horizon (synthesis §0) is where the edge actually lives. |

**Why separate from portfolio metrics:** a strategy can have a good Sharpe from a few lucky large positions while most signals are noise (or vice versa). Signal accuracy and hit-rate-by-sector isolate predictive quality from sizing/luck, which is what the Experiment Tracker needs to compare scorer versions.

---

## 3 — `summarize_performance` envelope

`summarize_performance(nav, trips, rf)` bundles the headline metrics into the exact shape `reporting-structure.md` and the Experiment Tracker consume without remapping:

```
{
  "returns": { total, annualized, benchmark, alpha, beta },
  "risk":    { sharpe, sortino, max_drawdown, calmar },
  "trades":  { win_rate, profit_factor, avg_win, avg_loss, win_loss_ratio }
}
```

`trades` is `{}` when no closed trips exist yet (early in a run) — callers must tolerate the empty dict.

---

## 4 — Performance thresholds ("what good looks like")

Encoded as the frozen dataclass `PerformanceThresholds`. These describe **evaluation**, not strategy behavior, so they live in code here — *not* in `strategy.yaml` (which holds only signal weights/parameters per CLAUDE.md). They are **starting points to be recalibrated by the Experiment Tracker after backtesting**, not claims about expected performance.

| Field | Value | Meaning |
|---|---|---|
| `sharpe_good` / `sharpe_warn` | `1.0` / `0.0` | ≥1.0 = algorithm is earning its risk; <0 = losing vs risk-free → red alert |
| `sortino_good` | `1.5` | downside-adjusted target (higher than Sharpe — penalizes only bad vol) |
| `max_drawdown_warn` / `_bad` | `-0.10` / `-0.20` | >10% underwater = caution; >20% = breach → red, investigate de-risking |
| `calmar_good` | `0.5` | return per unit of worst-case pain |
| `win_rate_min` | `0.45` | a trend strategy can win <50% if winners > losers — pair with profit factor |
| `profit_factor_good` / `_min` | `1.5` / `1.0` | <1.0 = strategy loses money gross; ≥1.5 = healthy |
| `signal_accuracy_min` | `0.52` | must beat a coin flip with margin, else signals aren't predictive |
| `alpha_good` | `0.0` | any positive annualized alpha beats buy-and-hold SPY |

**Headline health rule:** the simulation is "working" when, over a meaningful sample (≥ ~30 closed trips and ≥ ~3 months of NAV), **Sharpe ≥ 1.0, max drawdown shallower than −20%, profit factor ≥ 1.5, and alpha > 0**. Win rate alone never decides health — it is always read together with profit factor (a 45% win rate with PF 1.8 is excellent; a 60% win rate with PF 0.9 is broken).

---

## Handoff notes

**What I produced**
- This document — definitions, formulas, conventions, and thresholds for the full performance layer.
- `backend/analysis/performance/metrics.py` — all metric functions as pure, DataFrame-in / typed-result-out functions, plus `build_round_trips` (FIFO matcher), `PerformanceThresholds`, and the `summarize_performance` envelope.

**For the AI Engineer**
- `summarize_performance(nav, trips, rf)` is the single entry point — call it from the analysis/reporting path; don't re-derive metrics. Read `risk_free_rate_from_env()` once at the boundary and pass the float in (keeps the functions pure and testable).
- Build the trips frame with `build_round_trips(orders)` from the `trade_orders` log; pass the result to all trade-level and holding-period functions. Open positions intentionally produce no trip.
- Signal-quality functions depend on a **settle job** populating `algorithm_signals.realized_return`/`outcome`. Until that job exists, `signal_accuracy` returns `nan` (no settled rows) — that is expected, not a bug.

**For the Frontend Developer — what to display**
- **Performance card / hero strip:** Total Return %, CAGR, Sharpe, Sortino, Max Drawdown (with recovery state), Calmar, Alpha, Beta. Color each against `PerformanceThresholds` (good = green, warn = amber, bad/breach = red); render `nan` as "—".
- **Drawdown:** show current underwater state and the worst peak→trough→recovery span; if `recovery_ts is None`, label "not recovered".
- **Trade stats panel:** Win Rate, Profit Factor, Avg Win vs Avg Loss (paired bar). Always show win rate *next to* profit factor — never alone.
- **Signal quality view:** overall signal accuracy, hit-rate-by-sector (bar by sector), and the holding-period profitability table (validates the 1–4 week horizon). Surface "n settled signals" so users know the sample size behind the accuracy number.

**Open questions / deferred**
- **Column-name reconciliation:** schema `portfolio_nav` calls the benchmark column `benchmark`; `metrics.py` defaults its `benchmark_column` param to `benchmark_value`. Backend Architect should either name the column `benchmark` and pass `benchmark_column="benchmark"`, or align on one name. Flagging for confirmation — the function is parameterized so this is a wiring decision, not a code change.
- **Threshold recalibration** is owned by the Experiment Tracker post-backtest; the defaults here are deliberately conservative placeholders.
- **Commissions/slippage:** Phase 1 PaperBroker is frictionless, so trip P&L is gross. When the BrokerAdapter seam carries real costs, `build_round_trips` should subtract per-fill costs from `pnl` — the round-trip shape already isolates entry/exit, so this is additive.
