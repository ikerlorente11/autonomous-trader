<!-- Agent: Data Engineer | Phase: 4 | Depends on: Software Architect (protocols.py, contracts.py), Database Optimizer (models.py, schema.md), Investment Researcher (00-signal-synthesis.md) -->

# Data Ingestion Pipeline

OHLCV ingestion for the Tier-1 backbone: fetch daily bars, validate quality, and
upsert idempotently into `market_bars`. Built to the `MarketDataProvider` Protocol so
analysis never imports a concrete source.

## Modules

| File | Responsibility |
|---|---|
| `errors.py` | `ProviderError`, `RateLimitError(ProviderError)` — the fallback signal. |
| `calendar.py` | `pandas_market_calendars` wrapper: `is_trading_day`, `trading_days`, `previous_trading_day`. Exchange via `MARKET_CALENDAR` (default NYSE). |
| `validation.py` | Pure checks → `ValidationReport`: missing sessions, stale data, >threshold daily moves, empty symbols. |
| `providers/yfinance_provider.py` | Primary. Batched `yf.download`, thread-offloaded, normalised to UTC `OHLCVBar`. |
| `providers/twelve_data_provider.py` | Fallback. `httpx` async, comma-batched, 429 retry/backoff. |
| `ingest.py` | Orchestrator: provider selection, single-hop fallback, idempotent upsert, `ingest_daily_bars()`. |

## Contract conformance

- Returns `Mapping[str, list[OHLCVBar]]` (frozen pydantic DTO) — **not** DataFrame.
  The activation prompt mentioned DataFrame; the real `protocols.py` defines
  `OHLCVBar`, which is authoritative.
- All three protocol methods implemented on both providers. `get_available_symbols`
  returns `[]` (watchlist is runtime-populated per CLAUDE.md, not provider-derived).

## Idempotency

`upsert_bars()` uses `INSERT ... ON CONFLICT (symbol, ts) DO UPDATE` against the
`(symbol, ts)` composite PK. Re-running the same day overwrites the row in place — no
duplicates. The whole `ingest_daily_bars` path is safe to re-run.

## Configuration (env vars, no hardcoded values)

| Var | Default | Purpose |
|---|---|---|
| `MARKET_DATA_PROVIDER` | `yfinance` | Primary provider; the other is the fallback. |
| `MARKET_CALENDAR` | `NYSE` | Exchange calendar. |
| `PRICE_ANOMALY_PCT` | `0.50` | Daily close-to-close move flagged as suspicious. |
| `DATA_STALE_MAX_AGE_DAYS` | `4` | Sessions since last bar before "stale". |
| `TWELVE_DATA_API_KEY` | — | Required only when Twelve Data is used. |
| `TWELVE_DATA_BATCH` | `8` | Symbols per Twelve Data request (free-tier quota). |

## Handoff notes

**For Backend Architect:**

- **What I produced:** the full ingestion layer listed above + `requirements-data.txt`
  (`yfinance`, `httpx`, `pandas`, `pandas-market-calendars` — all ARM64-OK).
- **Scheduler entry point:** call `await ingest_daily_bars(session, symbols, start, end)`
  from the `06:30 fetch_market_data()` job. It fetches, validates, upserts, and commits.
  Gate it with `is_trading_day(today)` before spending API quota.
- **Session:** `upsert_bars`/`ingest_daily_bars` take an `AsyncSession`; use
  `backend.db.session.async_session`. `ingest_daily_bars` commits internally — do not
  wrap it in an outer transaction that also commits.
- **Symbols come from the `watchlist` table** (runtime), never hardcoded here. The job
  must load symbols from DB and pass them in.
- **Fallback is single-hop** by design: primary → secondary once → log + re-raise. The
  job should treat a raised `ProviderError` as "today's fetch failed" and rely on
  `misfire_grace_time` / next-day retry, not loop.
- **`ValidationReport.ok`** is returned but not enforced — bars are still written so
  analysis has *something*. Decide downstream whether a non-`ok` report should block
  the `run_analysis` job.

**Open questions / deferred:**

- `fetch_latest_price` uses a recent-bars window (yfinance has no clean async quote).
  Fine for daily cadence; revisit if intraday valuation is ever needed.
- Twelve Data free tier also caps requests/minute; only daily quota + 429 backoff are
  handled. If batch count grows, add a per-minute limiter.
- Twelve Data has no split-adjusted column on `/time_series`, so `adj_close` mirrors
  `close` there. yfinance provides real `Adj Close`. Acceptable while yfinance is
  primary; flag if Twelve Data becomes primary.
