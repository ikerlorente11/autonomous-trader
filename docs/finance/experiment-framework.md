<!-- Agent: Experiment Tracker | Phase: 2 | Depends on: docs/research/00-signal-synthesis.md, docs/finance/reporting-structure.md, docs/finance/performance-metrics.md (Financial Analyst — pending), docs/architecture/schema.md, backend/db/models.py -->

# Phase 2 — Experiment Framework

How the system records **which version of the scoring algorithm was active**, attributes every signal and trade to that version, and compares versions objectively over time. The strategy will be iterated; this framework makes each iteration a labelled, reproducible, comparable experiment.

> **Separation of concerns.** FP&A (`reporting-structure.md`) reports *money* (P&L, NAV, attribution). The Financial Analyst (`performance-metrics.md`, pending) owns the *risk/return formulas* (Sharpe, Sortino, max drawdown, Calmar, alpha). This document owns *algorithm credit*: tagging outputs with a version and comparing versions. It **consumes** the other two — it never redefines a metric. The comparator's join surface is FP&A's `summary.json` schema (§5.3 there), emitted using Financial Analyst formulas.

---

## SECTION 1 — THE EXPERIMENT MODEL

An **experiment** is one continuous period during which a single, frozen strategy configuration was live. In Phase 1 there is exactly one paper portfolio, so experiments are **sequential time slices**, not parallel arms (see §3.4 — this is the framework's central honesty constraint).

### 1.1 What an experiment is

| Field | Meaning | Storage |
|---|---|---|
| **`strategy_version`** | The version identifier (§2.1) — the join key for every signal/trade | `experiment_runs.strategy_version` |
| **Config snapshot** | The *fully resolved* `config/strategy.yaml` (all weights, thresholds, switches) as it was at start | `experiment_runs.config` (JSONB) |
| **`started_at`** | First timestamp this version was live | `experiment_runs.started_at` |
| **`ended_at`** | When superseded; `NULL` = currently active | `experiment_runs.ended_at` |
| **Results** | Frozen `summary.json` (FP&A §5.3 shape) computed for the window | `experiment_runs.results` (JSONB) — **proposed, see §5** |
| **Notes** | Human annotation ("raised momentum weight 0.3→0.4") | `experiment_runs.notes` |

The `experiment_runs` table already exists (`backend/db/models.py:139`) with all of the above except **`results`**. That column is the only schema addition this framework asks for (§5, flagged for Database Optimizer).

### 1.2 Config snapshot — why it is stored, not referenced

`config/strategy.yaml` is mutable and lives outside the DB. If an experiment only referenced "the yaml," the file would change under it and the experiment would no longer be reproducible. So at run-open the tracker serialises the **resolved pydantic config object** (synthesis §7: "typed config schema the engine validates at startup") into `experiment_runs.config`. This frozen JSONB is the ground truth for *what that version actually was*, independent of later edits.

### 1.3 Result isolation

Results for version *V* are every row attributable to *V*. Two complementary isolation keys:

1. **Direct tag (authoritative):** `trade_orders.strategy_version` and `algorithm_signals.strategy_version` carry *V* on each row. This survives even if run windows are later edited.
2. **Time window (cross-check):** `[started_at, ended_at)` on `experiment_runs`. Used to slice `portfolio_nav` (which has no per-row version — NAV is a single global series) and to validate that tagged rows fall inside the run window.

> **NAV caveat:** because there is one portfolio, the NAV series is shared. An experiment's return is the NAV slice over its `[started_at, ended_at)` window. This means **carry-over positions** opened by version *V1* but sold under *V2* attribute their holding-period NAV change partly to each window. We accept this (Phase 1, sequential sim) and flag it: per-trade realized P&L is cleanly versioned via the order tag; the NAV-window return is the honest-but-blunt portfolio view. Do not double-count one against the other — NAV-window return is authoritative for portfolio comparison, order tags for signal/trade attribution.

---

## SECTION 2 — VERSION TRACKING

### 2.1 The version identifier

```
strategy_version = "{semver}+{config_hash}"     e.g.  "v1.2.0+a3f9c1"
```

- **`semver`** — human intent, a `version:` key in `config/strategy.yaml`. Bumped deliberately by whoever changes the strategy (major = profile/structure change, minor = weight/threshold change, patch = fix).
- **`config_hash`** — first 6 hex chars of a SHA-256 over the *canonicalised resolved config* (sorted keys, normalised numbers). This is the safety net: if anyone edits a weight but forgets to bump `semver`, the hash changes and the system records a **distinct** version anyway. You can never silently attribute two different configs to one label.

### 2.2 Assignment at startup (the only place version is decided)

The scheduler process owns version assignment. On startup, before any job runs:

```
scheduler.main → ExperimentTracker.ensure_active_run(resolved_config)
```

`ensure_active_run` logic:
1. Compute `candidate = compute_strategy_version(resolved_config)`.
2. Read the currently-open run (`ended_at IS NULL`).
3. **If none** → open a new run (`started_at = now`, snapshot config). First boot.
4. **If open run's version == candidate** → no-op, reuse it. (Restart, same config.)
5. **If open run's version != candidate** → config changed: set the old run's `ended_at = now`, finalise its results (§5), then open a new run for `candidate`.

The resulting active `strategy_version` is held in process and exposed via `ExperimentTracker.current_version()`.

### 2.3 Stamping signals and trades

Every job that writes a `trade_order` or `algorithm_signal` reads `current_version()` and writes it onto the row:

```
run_analysis()         → algorithm_signals.strategy_version = current_version()
execute_paper_trades() → trade_orders.strategy_version      = current_version()
```

- `trade_orders.strategy_version` **already exists** (`models.py:103`).
- `algorithm_signals.strategy_version` **does not exist yet** — the brief requires it. **Flagged for Database Optimizer** (§5). Until added, signal-level version attribution falls back to the time-window join (§1.3), which is lossy across same-day version switches. The column is the correct fix.

> Stamping happens at the *write boundary* (Backend Architect's jobs / PortfolioManager), not inside the scorer. The scorer stays version-agnostic; the tracker injects identity. This keeps the BrokerAdapter/analysis seams clean.

---

## SECTION 3 — COMPARISON FRAMEWORK

Compare experiment *A* vs experiment *B*. Output feeds the comparator API and the dashboard's comparison view.

### 3.1 Standardised metrics (one source, no recompute)

The comparison consumes each run's frozen `summary.json` (FP&A §5.3) — **identical keys, Financial Analyst formulas**:

| Group | Keys | Owner |
|---|---|---|
| Returns | `total`, `annualized`, `benchmark`, `alpha` | FP&A envelope / FA formula |
| Risk | `sharpe`, `sortino`, `max_drawdown`, `calmar` | Financial Analyst |
| Activity | `trades`, `win_rate`, `profit_factor`, `avg_exposure` | FP&A |
| Signal quality | `signal_count`, `hit_rate` (from `monthly_signal_accuracy` CA / settled `algorithm_signals.outcome`) | Experiment Tracker |

The comparator computes **deltas** (B − A) per key and a percent change, never re-deriving the underlying numbers.

### 3.2 Statistical significance — is the difference real or noise?

A raw "B returned +1.2% more" is meaningless without a significance read. The comparator attaches a significance verdict to the headline comparisons:

| Comparison | Test | Why |
|---|---|---|
| Daily-return mean (A vs B) | **Paired/independent bootstrap** of daily returns (10k resamples) | Returns are non-normal, fat-tailed, small-n — bootstrap beats a t-test's normality assumption |
| Sharpe difference | **Jobson–Korkie with Memmel correction** | Sharpe ratios have known sampling variance; this is the standard test for ΔSharpe |
| Hit-rate / win-rate (A vs B) | **Two-proportion z-test** (or Fisher's exact when trade counts are low) | Binary outcomes, count-based |

Each test returns `{statistic, p_value, ci_low, ci_high, significant: bool}` at a configurable α (default 0.05). The framework **reports the verdict; it does not hide an insignificant result** — "no significant difference (p=0.34)" is a first-class, valuable answer that prevents over-fitting to noise.

### 3.3 Minimum-evidence gates

Before a comparison is even labelled "decisive," guard rails (configurable in `strategy.yaml` under an `experiment:` block):

- **≥ 30 trading days** of NAV per side (≈ 6 weeks) — below this, return stats are unstable.
- **≥ 30 closed trades** per side for trade-level stats (win rate / profit factor).
- **Settled signals only** for hit-rate: a signal's `outcome` is `NULL` until the settle job fills `realized_return` (schema.md note — forward returns must be known). Unsettled signals are excluded.

Below a gate, the comparator returns the metrics but marks the verdict `INSUFFICIENT_EVIDENCE`.

### 3.4 The confounding caveat — read this before trusting any A/B result

Because Phase 1 runs **one portfolio sequentially**, A and B almost always live in **different market regimes** (synthesis §4: RISK_ON / CAUTION / RISK_OFF). "v2 beat v1" may simply mean "v2 happened to run during a bull market." This is the single biggest threat to validity. Mitigations the framework provides:

1. **Regime tagging:** every comparison reports the regime mix (% of days RISK_ON/CAUTION/RISK_OFF, from `portfolio_nav.regime` / market_sentiment) for each side, so a viewer sees the confound.
2. **Regime-conditional comparison:** where both runs share enough days in the same regime, compare *within* regime (e.g., "in RISK_ON days only, B's Sharpe was X vs A's Y").
3. **Benchmark-relative metrics preferred:** `alpha` (excess vs SPY over the *same* window) partly neutralises regime, since SPY moved in that regime too. The framework foregrounds alpha over raw return in version comparisons.
4. **Future (Phase 2):** true parallel shadow experiments (multiple virtual portfolios scored by different versions on identical data) eliminate the confound. The schema (`experiment_runs` + per-row version tags) already supports this; only the PortfolioManager needs multi-book support. Flagged as out-of-scope now, designed-for later.

### 3.5 Visualisation data format (for comparison charts)

The comparator emits a single chart-ready payload the Frontend Developer can render without further math:

```json
{
  "a": {"strategy_version": "v1.0.0+e2b4", "summary": { ... FP&A summary.json ... }},
  "b": {"strategy_version": "v1.2.0+a3f9", "summary": { ... }},
  "equity_curves": {
    "a": [{"t": "2026-01-02", "rebased": 100.0}, {"t": "2026-01-03", "rebased": 100.4}],
    "b": [{"t": "2026-03-01", "rebased": 100.0}, {"t": "2026-03-02", "rebased": 99.7}]
  },
  "metric_deltas": [
    {"key": "sharpe", "a": 1.12, "b": 1.31, "delta": 0.19, "pct": 0.17,
     "significance": {"p_value": 0.08, "significant": false}}
  ],
  "regime_mix": {"a": {"RISK_ON": 0.7, "CAUTION": 0.2, "RISK_OFF": 0.1},
                 "b": {"RISK_ON": 0.3, "CAUTION": 0.3, "RISK_OFF": 0.4}},
  "verdict": "INSUFFICIENT_EVIDENCE | NO_SIGNIFICANT_DIFFERENCE | B_BETTER | A_BETTER"
}
```

- **Equity curves are rebased to 100** at each run's own start, so two runs of different windows/sizes overlay on one axis (relative shape comparison, not absolute NAV).
- `metric_deltas` is a flat array → trivial to render as a diff table with significance badges.
- `regime_mix` makes the §3.4 confound visible on the chart, not buried.

---

## SECTION 4 — IMPLEMENTATION

Module skeleton at `backend/experiments/`. Stubs with full typed interfaces, minimal bodies — the AI Engineer fills logic.

| File | Responsibility |
|---|---|
| `__init__.py` | Public exports (`ExperimentTracker`, `ExperimentComparator`, dataclasses) |
| `tracker.py` | Resolve version from config; open/close/finalise runs in DB; expose `current_version()` for stamping |
| `comparator.py` | Load run summaries, compute deltas, run significance tests, emit chart payload |

Public dataclasses (`ExperimentSummary`, `MetricDelta`, `SignificanceResult`, `ComparisonResult`) mirror the §3.4 payload and FP&A's `summary.json`, so the API layer serialises them directly.

---

## SECTION 5 — SCHEMA REQUESTS (for Database Optimizer)

Two changes, both small and additive:

1. **`algorithm_signals.strategy_version`** `VARCHAR(64) NULL` + index `(strategy_version, ts)`. **Required by the brief** — currently absent (`models.py:109`). Without it, signal-level version attribution is time-window-only and lossy across intra-day version switches.
2. **`experiment_runs.results`** `JSONB NULL`. Stores the frozen `summary.json` per run so comparisons are O(1) reads, survive data archival/compression, and don't recompute from raw rows each time. Optional-but-recommended; the comparator can fall back to on-the-fly computation from tagged rows if absent.

Both are nullable/additive → a forward-only Alembic migration, no backfill needed (legacy rows simply carry `NULL`).

---

## Handoff notes

**What this document produced:** the experiment model (version + frozen config snapshot + window + frozen results), the version-identifier scheme (`semver+config_hash`) with startup assignment and write-boundary stamping, the comparison framework (FP&A summary.json as join surface, bootstrap / Jobson–Korkie / two-proportion significance tests, minimum-evidence gates, the regime-confound caveat and mitigations), the chart-ready comparison payload, and the `backend/experiments/` skeleton.

**For the AI Engineer:**
- The scorer must stay **version-agnostic**. Version identity is injected by the tracker at the job write boundary, not computed inside the scorer. Call `ExperimentTracker.ensure_active_run(resolved_config)` once at scheduler startup; call `current_version()` when writing `algorithm_signals` / `trade_orders`.
- `compute_strategy_version(config)` must hash the **resolved** config (post-pydantic-validation, defaults applied), with canonical key ordering, so the hash is stable across yaml formatting changes.
- Implement the significance tests in `comparator.py` against `scipy`/`numpy` (confirm these fit the Pi RAM budget — both are ARM64-available; keep resamples bounded, e.g. 10k, to stay within the scheduler's peak budget).
- Honour the `experiment:` config block (α, minimum-evidence gates) — do not hardcode 0.05 or the day/trade thresholds.

**For Analytics Reporter:**
- Verify the dashboard's version-comparison view renders the §3.4 payload: dual rebased equity curves, metric-delta table **with significance badges**, and the **regime-mix** panel. A comparison shown without regime context is a validity bug — flag it.
- Confirm `INSUFFICIENT_EVIDENCE` and `NO_SIGNIFICANT_DIFFERENCE` verdicts are surfaced, not silently dropped — preventing over-fitting to noise is the whole point.
- Cross-check that every `trade_orders` and `algorithm_signals` row in a populated DB carries a non-null `strategy_version` (post-migration). Orphan (null-version) rows after the schema change indicate a stamping bug in the jobs.

**Open questions / deferred:**
- **Blocked on Financial Analyst** (`performance-metrics.md`): the exact `risk` formulas behind the `sharpe/sortino/max_drawdown/calmar` keys the comparator deltas. The comparator treats them as opaque numbers from `summary.json`, so it is unblocked *structurally*, but verdict thresholds may want tuning once formulas land.
- **Schema additions (§5)** require Database Optimizer sign-off before the tracker can stamp signals or store frozen results.
- **Parallel shadow experiments** (§3.4 mitigation 4) deferred to Phase 2 — needs multi-book PortfolioManager; schema already supports it.
