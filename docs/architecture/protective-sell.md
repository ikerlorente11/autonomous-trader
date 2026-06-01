<!-- Agent: Claude | Phase: post-5 | Depends on: scheduler/jobs, trading/paper_broker, data_ingestion (yfinance live), db migration 0006 -->

# Intraday protective sell (trailing stop)

## Why

The daily pipeline analyses at 07:30 UTC and trades at 08:00 UTC on the **daily close**.
Between runs it is blind: if a held position crashes mid-session it isn't sold until the next
day, and only if the *daily score* decays below the exit threshold. There was **no
position-level stop-loss**. This feature adds an intraday guard that cuts losses — and locks in
gains — without waiting for the daily cycle.

## What it does

`protective_sell` ([backend/scheduler/jobs.py](../../backend/scheduler/jobs.py)) is an
APScheduler **interval** job (every `PROTECTIVE_SELL_INTERVAL_MIN`, default 15 min). It:

1. No-ops outside market hours (`calendar.is_market_open_now`) and when
   `PROTECTIVE_SELL_ENABLED=false`.
2. Reads a live-VIX **regime** once per run (see below).
3. For each active portfolio, fetches live prices for its open positions (falling back to the
   latest stored close if a live quote is missing), ratchets each position's
   `high_water_mark`, and **sells in full** any position whose price has retraced past the
   trailing stop from its peak.

Sells go through the unchanged `BrokerAdapter` seam (`place_order(..., "sell", ...)`) and are
tagged `strategy_version='protective-sell'` so they're distinguishable in the trades table.
Before each sell the live price is marked as today's bar (`upsert_bars`) so the simulated fill
is realistic; the next morning's `fetch_market_data` overwrites it, keeping the daily series
canonical.

## Stop logic

Pure maths live in [backend/trading/stops.py](../../backend/trading/stops.py)
(`evaluate_trailing_stop`, `stop_distance`, `regime_adjustment`).

- **High-water mark** seeds from `avg_cost` and only ratchets up — so a position that only ever
  falls still has a hard floor, while one that runs up trails its peak (take-profit).
- **Stop distance** = `ATR(14) × STOP_ATR_MULTIPLE` when a raw ATR is available (volatility-
  adaptive — wider for choppy names), else `peak × TRAILING_STOP_PCT`. The raw ATR is computed
  on the fly from stored daily bars via `AverageTrueRangeIndicator`. (Note: the persisted
  `signal_values` "atr" is a 0–100 sub-score, not price units — hence the recompute.)
- **Regime** (live `^VIX`): at/above `VIX_TIGHTEN_ABOVE` the stop distance is multiplied by
  `STOP_TIGHTEN_FACTOR` (< 1 → exit sooner); at/above `VIX_PANIC_ABOVE` the job **holds**
  (suspends selling) — extreme VIX is historically near the bottom, so don't sell the
  capitulation. Set `VIX_PANIC_HOLD=false` to always protect instead.

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `PROTECTIVE_SELL_ENABLED` | `true` | Master switch (also gates scheduler registration). |
| `PROTECTIVE_SELL_INTERVAL_MIN` | `15` | Minutes between checks during market hours. |
| `TRAILING_STOP_PCT` | `0.08` | Retrace from peak that triggers a sell (fallback / no-ATR). |
| `STOP_ATR_MULTIPLE` | `2.5` | Stop distance = ATR × this. `0` → always use the %. |
| `STOP_REGIME_ENABLED` | `true` | Read live VIX and adjust the stop. |
| `VIX_TIGHTEN_ABOVE` / `STOP_TIGHTEN_FACTOR` | `30` / `0.6` | Stress: tighten the stop. |
| `VIX_PANIC_ABOVE` / `VIX_PANIC_HOLD` | `40` / `true` | Panic: hold (don't sell the bottom). |

## Wiring

- **Not** in `JOB_SCHEDULE` (the daily 4, shared with the API for next-run times). Registered
  separately as an `IntervalTrigger` in [scheduler/main.py](../../backend/scheduler/main.py),
  gated by `PROTECTIVE_SELL_ENABLED`; `coalesce`/`max_instances=1` prevent overlap.
- New nullable column `portfolio_positions.high_water_mark` (migration `0006`), initialized
  lazily on the first check — open positions need no backfill.
- **Ops:** the `scheduler` container has no hot-reload — `docker restart trader-scheduler`
  after changing this job (see the dev bind-mount note in CLAUDE.md / project memory).

## Reliability caveat

Live prices use Yahoo, whose endpoint 429s this deployment's IP. `fetch_live_prices` is
hardened (retry/backoff + rotating UA), and the job falls back to the stored close when a
live quote is unavailable — but a fully real-time guarantee would need a dedicated quote
provider. The daily pipeline is unaffected.

## Tests

- unit: `backend/tests/unit/test_stops.py` (pct / ATR distance / regime), `test_market_hours.py`.
- integration: `backend/tests/integration/test_protective_sell.py` (pct trigger, ATR trigger,
  hold-on-no-trigger with HWM ratchet, market-closed skip).

## Out of scope (future)

ATR-vs-%, regime tightening and the VIX panic floor are grounded in the research docs
(`docs/research/`), but a full macro regime (credit spreads, term structure, sector rotation)
still depends on the stubbed macro/sentiment ingestion. Pre-earnings de-risk and intraday
*buying* (momentum) were deliberately deferred.
