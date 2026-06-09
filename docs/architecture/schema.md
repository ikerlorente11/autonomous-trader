<!-- Agent: Database Optimizer | Phase: 1 | Depends on: docs/research/00-signal-synthesis.md -->

# Database Schema — TimescaleDB (PostgreSQL 16)

The complete persistence layer for the autonomous trader. All services communicate
**exclusively through this database** (CLAUDE.md). Volumes are tiny by design — the
synthesis doc (§2) sizes the universe at **66 tickers** (50 watchlist + ~16
macro/intermarket), ~16.6k rows/yr in `market_bars`; every other table is event-driven
or a market-wide daily singleton. Compression therefore matters only on `market_bars`
over multi-year history.

**18 tables** in three groups: time-series (hypertables), portfolio/trading, and
data ingestion. Plus **2 continuous aggregates**.

## Entity groups (text ER)

```
TIME-SERIES (hypertables) ─────────────────────────────────────────
  market_bars        (symbol, ts) PK · OHLCV daily bars
  signal_values      (symbol, ts, signal_id) PK · universal computed-signal store
  macro_series       (series_id, ts) PK · FRED macro values (+ release_ts)
  portfolio_nav      (ts) PK · daily NAV snapshot
  algorithm_signals  (symbol, ts) PK · per-run scores/actions (hypertable)

PORTFOLIO / TRADING ───────────────────────────────────────────────
  portfolio_positions (symbol) PK · current holdings
  trade_orders        (id) PK · simulated order log
  watchlist           (symbol) PK · tracked universe (populated at runtime)
  experiment_runs     (id) PK · strategy-run registry

INGESTION (event-driven / periodic) ───────────────────────────────
  fundamentals_quarterly (symbol, period_end) PK · quarterly statements (jsonb)
  earnings_calendar      (symbol, report_date) PK · upcoming reports
  earnings_estimates     (symbol, period_end) PK · consensus EPS + SUE (owns SUE)
  analyst_estimates      (symbol, as_of) PK · ratings / revisions
  insider_transactions   (accession_no, txn_seq) PK · Form 4 open-market txns
  sec_filings            (accession_no) PK · 8-K / 10-K / 10-Q events
  news_sentiment         (symbol, ts) PK · daily pre-scored news aggregate
  market_sentiment       (ts) PK · market-wide VIX / put-call / breadth / fear-greed
  short_interest         (symbol, settlement_date) PK · bi-monthly short interest
```

Relationships are **logical, not enforced FKs**: `symbol` is the common join key
across `watchlist`, `market_bars`, `signal_values`, `algorithm_signals`,
`portfolio_positions`, and all ingestion tables. No FK constraints are declared —
ingestion jobs may write a symbol's data before/after it enters the watchlist, and
hypertable FKs add write overhead for no integrity benefit in a single-writer pipeline.

## Table roles

| Table | Role |
|---|---|
| `market_bars` | Daily OHLCV for watchlist + intermarket/regime ETFs. The dominant table. Backtest + charting source. |
| `signal_values` | Every computed indicator/signal per symbol/date, plus `data_completeness` (§3.3). Flexible — new signals need no schema change. |
| `macro_series` | FRED series (rates, curve, CPI, LEI, claims…). `release_ts` preserves point-in-time vintage. |
| `portfolio_nav` | Daily cash/equity/total + benchmark for the equity curve and performance metrics. |
| `algorithm_signals` | Output of `run_analysis`: score, action, reason, full `indicator_snapshot` (jsonb). `realized_return`/`outcome` filled later by a settle job to feed `monthly_signal_accuracy`. |
| `portfolio_positions` | Current holdings with `unrealized_pnl`, refreshed on valuation. |
| `trade_orders` | Append-only simulated order log (`PaperBroker`). |
| `watchlist` | Tracked symbols + sector/asset_class. Empty at build time; populated at runtime from the synthesis seed — never hardcoded. |
| `experiment_runs` | Registry of strategy runs with `config` (jsonb) for the Experiment Tracker. |
| `fundamentals_quarterly` | Quarterly statement line items as jsonb (shapes vary by company). `as_of` for point-in-time. |
| `earnings_calendar` | Report dates for the de-risk window job. |
| `earnings_estimates` | Consensus + actual EPS and standardized `sue`. **Single owner of SUE**; PEAD reads it. |
| `analyst_estimates` | Mean rating, up/down counts, target — revision momentum input. |
| `insider_transactions` | Form 4 open-market buys/sells. `(accession_no, txn_seq)` makes re-scans idempotent. |
| `sec_filings` | 8-K/10-K/10-Q events with `item_codes` + keyword `polarity`. |
| `news_sentiment` | Daily per-symbol pre-scored news aggregate (count, mean, z-score). |
| `market_sentiment` | Market-wide daily gauge — VIX, term ratio, put/call, breadth, reconstructed fear/greed. |
| `short_interest` | Bi-monthly short shares + days-to-cover. |

## Hypertables, chunking, compression

| Hypertable | Time col | Chunk interval | Why |
|---|---|---|---|
| `market_bars` | `ts` | 1 month | ~1.4k rows/chunk (66 tickers × ~21 trading days) — efficient chunk pruning on range scans. |
| `signal_values` | `ts` | 1 month | Aligns with `market_bars`; daily compute volume. |
| `macro_series` | `ts` | 1 year | Series update infrequently and total volume is <1 MB; large chunks avoid chunk sprawl. |
| `portfolio_nav` | `ts` | 1 month | One row/day; small chunks keep recent-range NAV queries fast. |
| `algorithm_signals` | `ts` | 1 month | Made a hypertable so `monthly_signal_accuracy` (a continuous aggregate) can read it. |

**Compression:** only `market_bars` —
`ALTER TABLE market_bars SET (timescaledb.compress, compress_segmentby='symbol', compress_orderby='ts DESC')`
with `add_compression_policy('market_bars', INTERVAL '180 days')`. Six months of recent
bars stay uncompressed for fast writes/reads; older history compresses (segmented by
symbol, ordered by ts) for multi-year backtests. No other table has the volume to justify it.

## Index strategy (each justified; none speculative)

| Index | Table | Serves |
|---|---|---|
| PK `(symbol, ts)` | `market_bars` | Per-symbol range scans (`get_bars_range`), idempotent upsert, `DISTINCT ON (symbol) … ts DESC` latest bar (`get_latest_bars`). |
| `ix_signal_values_symbol_signal_ts (symbol, signal_id, ts)` | `signal_values` | `get_signal_series` (symbol + signal filter over time); the PK leads with `ts` second, so a dedicated index is needed for the signal-scoped scan. |
| `ix_trade_orders_ts (ts DESC)` | `trade_orders` | `get_recent_orders` — `ORDER BY ts DESC LIMIT`. |
| `ix_algorithm_signals_ts_score (ts, score DESC)` | `algorithm_signals` | `get_top_ranked_signals` — latest date, score desc; also the `monthly_signal_accuracy` scan. |
| `ix_insider_symbol_filed (symbol, filed_ts)` | `insider_transactions` | Recent insider activity per symbol for the smart-money signal. |
| `ix_sec_filings_symbol_filed (symbol, filed_ts)` | `sec_filings` | Recent filings per symbol for 8-K detection. |
| `ix_earnings_calendar_report_date (report_date)` | `earnings_calendar` | De-risk-window job scans upcoming reports across all symbols by date. |

**Deliberately no extra index** on `macro_series`, `portfolio_nav`, `news_sentiment`,
`short_interest`, `fundamentals_quarterly`, `earnings_estimates`, `analyst_estimates`,
`market_sentiment` — their PK already matches their only access pattern. **No index** on
`watchlist` or `portfolio_positions` — ~50 rows each; a sequential scan is faster than an
index lookup and cheaper to maintain. The Timescale time-dimension index auto-created on
each hypertable's `ts` serves the cross-sectional `get_latest_signal_snapshot` and the
NAV range scan.

## Continuous aggregates

| CA | Source | Bucket | Columns | Refresh policy |
|---|---|---|---|---|
| `weekly_performance` | `portfolio_nav` | `time_bucket('7 days', ts)` | first/last of total, cash, equity; last benchmark | start 90d / end 1d / every 7d |
| `monthly_signal_accuracy` | `algorithm_signals` | `time_bucket('30 days', ts)` | `signal_count`, `avg_score`, `hit_rate = avg(outcome='correct')` over settled rows | start 180d / end 1d / every 30d |

Notes:
- **30 days, not calendar-month:** continuous aggregates over a `timestamptz` hypertable
  need a fixed-width bucket (or an explicit timezone arg). A fixed 30-day bucket is robust
  on the Pi and avoids timezone-dependent refresh edge cases. The name is kept for clarity.
- `hit_rate` aggregates the **pre-computed** `outcome` column, so the CA stays a pure
  aggregate — no forward-looking join. A downstream settle job (Experiment Tracker / a
  dedicated scorer-settlement job) fills `realized_return` + `outcome` once forward
  returns are known.
- Created `WITH NO DATA`; the refresh policy backfills. CA DDL runs in an
  `autocommit_block()` because it cannot execute inside a transaction.

## Point-in-time & idempotency (synthesis §6)

- **Revision hazard:** FRED series (CPI, NFP, LEI) and yfinance fundamentals are
  *restated*. `macro_series.release_ts`, `fundamentals_quarterly.as_of`, and
  `earnings_estimates.as_of` capture when a value was published, so the Experiment
  Tracker can avoid look-ahead bias. Full FRED/ALFRED vintage history is a Phase-2 upgrade.
- **Idempotent upserts everywhere** (jobs may rerun within `misfire_grace_time=3600`).
  Natural keys: bars `(symbol, ts)`, signals `(symbol, ts, signal_id)`, macro
  `(series_id, ts)`, filings `(accession_no)`, insider `(accession_no, txn_seq)`,
  fundamentals `(symbol, period_end)`. Writers use `INSERT … ON CONFLICT (…) DO UPDATE`.

## Migrations

- `0001_initial_schema` — extension, 18 tables, 5 hypertables, indexes, `market_bars` compression.
- `0002_continuous_aggregates` — the 2 CAs + refresh policies (autocommit_block).
- `0003_algorithm_signals_strategy_version` — `strategy_version` on `algorithm_signals`.
- `0004_job_runs` — `job_runs` audit table.
- `0005_multi_portfolio` — `portfolios` + `cash_movements`; `trade_orders`/`portfolio_positions`/
  `portfolio_nav` scoped by `portfolio_id` (composite PKs; NAV CA regrouped by portfolio).
- `0006_signal_completeness_indexes` — supporting indexes.
- `0007_position_high_water_mark` — `portfolio_positions.high_water_mark` (trailing stop).
- `0008_portfolio_strategy_label` — **`portfolios.strategy_label`** (nullable). Per-portfolio
  **strategy version** for A/B: NULL = base config; a label resolves to
  `config/strategies/<label>.yaml` deep-merged onto `config/strategy.yaml`. The daily engine
  trades each portfolio under its own version. See `docs/diagnostics/02-plan-mejora.md` and `CLAUDE.md`.
- `0009_trade_orders_commission` — **`trade_orders.commission`** (nullable; P10). Per-order
  commission cost charged by `PaperBroker` (`COMMISSION_PCT`/`COMMISSION_PER_ORDER`, default 0).
  `compute_cash` subtracts Σcommission, so it drags cash/NAV but **not** contributed capital.
  NULL backfilled to 0, so historical portfolios' cash is unchanged. See `docs/diagnostics/03-plan-v3.md`.

Run with `DATABASE_URL` set (asyncpg URL, e.g. `postgresql+asyncpg://user:pass@host/db`):
`cd backend/db/migrations && alembic upgrade head`.

## Handoff notes

**Produced:** full TimescaleDB schema as Alembic migrations (`backend/db/migrations/`),
SQLAlchemy 2.x async models (`backend/db/models.py`), shared `Base`/engine
(`backend/db/base.py`, `session.py`), 10 parameterized queries
(`backend/db/queries/{market,portfolio}_queries.py`), and this doc.

**For the Data Engineer (Phase 4):**
- Upsert keys are listed above — use `INSERT … ON CONFLICT DO UPDATE` for every writer.
- `signal_values` is the universal sink for any computed signal; `signal_id` is a free
  string — no migration needed to add signals. Populate `data_completeness` per §3.3.
- Reuse `market_bars` for intermarket/regime ETFs (^VIX, HYG, RSP, …) — no separate table.
- Populate `release_ts`/`as_of` on macro + fundamentals from the source's publish date.
- `watchlist` ships empty; seed it at runtime from synthesis §5 (never hardcode in source).

**For the Backend Architect (Phase 4):**
- All query functions take `AsyncSession` as the first argument; wire them through the
  FastAPI dependency that yields from `async_session` (`backend/db/session.py`).
- `algorithm_signals.realized_return` + `outcome` need a **settle job** in the scheduler
  to make `monthly_signal_accuracy.hit_rate` meaningful (set `outcome='correct'` when the
  forward return confirms the action). Not yet implemented — flag for the AI/Backend phase.
- `trade_orders.id` and `experiment_runs.id` are DB-generated `BIGSERIAL`; everything
  else uses natural keys.
- Money/prices are `Numeric` (never float) — keep `Decimal` end-to-end through
  `PortfolioManager`/`PaperBroker`.

**Open decisions deferred:** FRED ALFRED vintage backfill (Phase 2); whether
`news_sentiment`/`market_sentiment` warrant hypertable conversion (left regular — daily
singleton volume doesn't justify it yet).
