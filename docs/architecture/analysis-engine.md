<!-- Agent: AI Engineer | Phase: 4 | Depends on: Software Architect (contracts, engine Protocol), Database Optimizer (schema), Financial Analyst (metrics), Experiment Tracker (strategy versioning), Investment Researcher (signal synthesis) -->

# Analysis engine

The configurable scoring engine: OHLCV bars -> per-symbol indicator sub-scores ->
weighted composite (0–100) -> ranked buy candidates. Weights and thresholds are
**all** in `config/strategy.yaml`; the code is structure only (CLAUDE.md).

## What was produced

| File | Role |
|---|---|
| `config/strategy.yaml` | Version-controlled defaults (synthesis §3.2 stubs): `version`, indicator params, weights, ranker cutoffs. |
| `backend/analysis/config.py` | `StrategyConfig` (frozen pydantic). YAML + env override (`STRATEGY__<SECTION>__<KEY>`). `strategy_version = "{semver}+{config_hash}"`. |
| `backend/analysis/indicators/base.py` | `Indicator` ABC: `compute(df)->Series`, `name`, `required_periods`, graceful all-NaN, `latest_score(df)->float\|None`. Helpers `clip_0_100`, `logistic_0_100`. |
| `indicators/moving_average.py` | `SimpleMovingAverage`, `ExponentialMovingAverage` (signal_id `ma_trend`). |
| `indicators/momentum.py` | `RelativeStrengthIndex` (`ta`, signal_id `rsi`, native 0–100 passthrough). |
| `indicators/volatility.py` | `AverageTrueRangeIndicator` (`ta`, signal_id `atr`). |
| `scoring/composite_scorer.py` | `CompositeScorer` Protocol + `WeightedCompositeScorer` (renormalize-on-missing, §3.3). |
| `scoring/symbol_ranker.py` | `SymbolRanker` Protocol + `ScoreRanker` (cutoffs + `exclude` set). |
| `scoring/persistence.py` | Idempotent upserts to `signal_values` and `algorithm_signals`. |
| `engine.py` | `AnalysisEngine` Protocol + `DefaultAnalysisEngine` wiring all of the above. |
| `db/models.py` + migration `0003` | Added `algorithm_signals.strategy_version` column. |
| `requirements-analysis.txt` | Added `ta==0.11.0`, `PyYAML==6.0.2`. |

## Decisions / deviations from LAUNCH_PROMPT

- **Table is `signal_values`, not `indicator_values`** (LAUNCH name was stale; real schema wins).
- **Added `algorithm_signals.strategy_version`** (migration 0003) — the experiment-framework requires per-row version tagging but the column was missing. Approved by user.
- **`strategy_version` is `{semver}+{config_hash}`**, not a bare env var (experiment-framework §2.1). `semver` is the yaml `version:` key; the hash makes an un-bumped edit record distinctly.
- **Scorer is pure** (Protocol seam): `score(symbol, indicators, asof)`. DB writes live in `persistence.py` (the session-aware layer), called by the scheduler — not inside the scorer.
- **Insufficient-data filtering happens in the engine** (a symbol with < `required_periods` bars yields no `IndicatorResult` and a low/zero-completeness `SymbolScore`); the ranker then drops it via the completeness floor. The ranker's `exclude` set carries validation-suspicious symbols.

## Handoff notes

### For the scheduler / Backend Architect (the caller wiring `run_analysis`)
- Resolve config **once at startup**: `cfg = load_strategy_config()`; build `DefaultAnalysisEngine(cfg)`. Use `engine.strategy_version` when persisting.
- Per day: load bars per symbol into a `Mapping[str, DataFrame]` (lowercase columns `open/high/low/close/volume`, ascending by date), then:
  `scores = [engine.score_symbol(sym, df, asof) for sym, df in bars.items()]` →
  `await persist_signal_values(session, engine.compute_indicators(bars, asof))` →
  `await persist_algorithm_signals(session, scores, engine.strategy_version)` →
  `ranked = engine.rank_symbols(scores)`. Caller owns `session.commit()` (writes are idempotent upserts — safe to re-run same day).
- Pass validation-suspicious symbols via `ScoreRanker.rank(scores, exclude=...)` if available from the ingest report.

### For the Frontend Developer
- `algorithm_signals` rows now carry `score` (0–100), `action` (`buy`/`hold`), `reason`, `indicator_snapshot` (jsonb `{signal_id: float}`), and `strategy_version`. The signals panel can read the snapshot directly to show per-indicator contributions; the version chip comes from `strategy_version`.
- Ranking order for the dashboard = `algorithm_signals` ordered by `score DESC` for the latest `ts` (index already exists).

### For the Analytics Reporter
- Data flow to verify: scheduler → `signal_values` (per-indicator) + `algorithm_signals` (composite) → API → UI. KPI completeness should check `indicator_snapshot` is non-empty and `data_completeness` is persisted on `signal_values`.
- Every `algorithm_signals` row must have a non-null `strategy_version` matching the active `experiment_runs.strategy_version`.

### Open questions / deferred
- **Cross-sectional rank-normalization (§3.4)** is not yet applied — sub-scores are currently per-symbol bounded (logistic) only. Add a universe-level normalization pass in the engine when the real signal set lands.
- **Sell logic**: `action` is `buy`/`hold` only; sell/exit signals are deferred to risk_manager/trading phase.
- **Local runtime check not possible**: analysis deps (`pydantic`, `pandas`, `ta`) aren't in the local env; only `py_compile` + YAML-schema checks were run here. Full execution validation runs in the Docker (Python 3.12) image.
