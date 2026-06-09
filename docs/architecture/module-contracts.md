<!-- Agent: Software Architect | Phase: 1 | Depends on: Phase 0 research, schema.md -->

# Module Contracts — Autonomous Trader

The internal contract layer: how every backend module imports, the Protocol seams,
the typed values passed between modules, the API surface the SvelteKit dashboard
consumes, and the configuration schema. The database layer (`backend/db/`) already
exists; **all contracts here align field-for-field with `backend/db/models.py`** and
respect exact column case. Nothing here defines business logic, weights, or
thresholds — those are configuration (`config/strategy.yaml`) per CLAUDE.md.

---

## 1. Module dependency graph

Arrows mean *imports from*. The graph is a DAG — **no cycles**. `backend.contracts`
and `backend.db.models` are leaf modules (depend on nothing internal), so every other
module can import them freely without risking a cycle.

```
                          ┌─────────────────────┐
                          │  backend.contracts   │  ← DTOs (Pydantic v2), leaf
                          └─────────┬───────────┘
        ┌───────────────────┬───────┼────────────────┬──────────────────┐
        ▼                   ▼       ▼                ▼                  ▼
 data_ingestion.      trading.        analysis.engine     analysis.scoring.   trading.
 protocols            broker_adapter  analysis.indicators  composite_scorer    risk_manager
 (provider Protocols) (sacred seam)   .base                symbol_ranker
        │                   │              ▲                      │
        │                   │              │ (concrete indicators)│
        │                   │      analysis.signals.{technical,fundamental,
        │                   │              macro,sentiment}  ← stubs only
        │                   │
        ▼                   ▼
 data_ingestion.      trading.paper_broker ─┐
 providers.*          trading.portfolio_     │ implements BrokerAdapter
 (Phase 4 impls)      manager ───────────────┘ (PortfolioManager depends on the
                                              Protocol, never a concrete broker)

 backend.db (pre-existing, leaf) ───────────────────────────────────────────
   db.base ◄── db.models ◄── db.queries.{market,portfolio}_queries
                  ▲                       ▲
                  │                       │ AsyncSession (db.session)
   db.session ────┘                       │
                                          │
 backend.api.main ──► api.routers.{portfolio,portfolios,market,trades,algorithms,system}
                          │  depend on: db.queries.*, db.session, backend.contracts
                          ▼
                  (response models = backend.contracts.*)

 backend.scheduler.{main,jobs} ──► data_ingestion.providers.* (fetch)
                                   ──► analysis.engine + scoring (run_analysis)
                                   ──► trading.portfolio_manager (execute trades)
                                   ──► db.queries.* (read/write via AsyncSession)

 backend.analysis.performance.metrics (pre-existing, pandas, leaf — pure math)
 backend.experiments.{tracker,comparator} (pre-existing) ──► db.models
```

### Dependency rules (enforced by review)
- **`backend.contracts` imports nothing internal.** It is the universal DTO leaf.
- **`PortfolioManager` imports `trading.broker_adapter` (the Protocol), never `paper_broker` directly.** The concrete broker is injected by env (`BROKER_ADAPTER`). This is the sacred seam.
- **Analysis never imports a concrete provider** and **never opens a session / calls an external API** — `run_analysis` reads from the DB via `db.queries` and computes (synthesis §6).
- **Providers never import analysis or trading** — they only produce `backend.contracts` DTOs.
- **API routers depend on `db.queries` + `backend.contracts` only** — no provider, no scheduler imports.
- The `analysis/signals/*` and `analysis/scoring/*` modules are **stubs** (Protocol/ABC interfaces); concrete logic arrives later. `trading/risk_manager.py` is **implemented in Phase 4** (`FixedFractionalRiskManager`), not a stub.

### Where data contracts live (and why)
DTOs live in a single leaf module **`backend/contracts.py`**, not per-domain files.
Rationale: (1) they are imported by every layer (providers, analysis, trading, api),
so a single leaf avoids any chance of an import cycle; (2) they are small and cohesive;
(3) one file is easy for the Backend Architect and Data Engineer to scan. They are
**deliberately distinct from the SQLAlchemy ORM models** in `backend/db/models.py`:
ORM rows are session-bound, mutable, and persistence-coupled, whereas these are
immutable (`frozen=True`), JSON-serialisable transfer objects FastAPI can emit
directly. **Field names and types mirror the matching DB columns 1:1**, so an adapter
can construct a DTO from a row without remapping.

---

## 2. Protocol definitions

All Protocols are `typing.Protocol`, `@runtime_checkable` where a runtime
`isinstance` check is useful for dependency injection. Real files are written to disk;
the canonical source is the path noted under each block.

### 2.1 `BrokerAdapter` — `backend/trading/broker_adapter.py` (SACRED)

```python
@runtime_checkable
class BrokerAdapter(Protocol):
    async def place_order(self, symbol: str, side: str, qty: Decimal, order_type: str) -> Order: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_account_balance(self) -> Decimal: ...
    async def get_cash(self) -> Decimal: ...
    async def get_order_status(self, order_id: str) -> OrderStatus: ...
```

The seam is **`async` with `qty: Decimal`** as CLAUDE.md blesses: the whole stack is
async SQLAlchemy and the real-broker swap target is network-bound, so every adapter
(`PaperBroker`, `MockRealBroker`, a future real one) is async; `Decimal` `qty`
supports fractional shares so a small budget can take a position in a high-priced
symbol. `get_account_balance()` returns the **total** (cash + equity) as a bare
`Decimal`. `get_cash()` is the cash component, broker-authoritative: `PortfolioManager`
assembles its `AccountBalance` (cash / equity / total) purely from `get_account_balance()`
+ `get_cash()` and must **not** read the DB cash ledger directly — otherwise an
in-memory adapter (`MockRealBroker`) would report a cash that does not reconcile with
its own total. Supporting types (`Order`, `Position`, `OrderStatus`) are re-exported
from `backend.contracts`.

### 2.2 `MarketDataProvider` (+ sub-protocols) — `backend/data_ingestion/protocols.py`

The brief requires `MarketDataProvider`; synthesis §6 requires more *shapes* than
OHLCV. `MarketDataProvider` is the OHLCV backbone; sibling sub-protocols cover the
rest. All I/O is `async`; all accept symbol **lists** for batched fetches on the Pi.

```python
@runtime_checkable
class MarketDataProvider(Protocol):
    async def fetch_daily_bars(self, symbols: Sequence[str], start: date, end: date) -> Mapping[str, list[OHLCVBar]]: ...
    async def fetch_latest_price(self, symbols: Sequence[str]) -> Mapping[str, Decimal]: ...
    async def get_available_symbols(self) -> list[str]: ...
```

Sub-protocols (same file): `FundamentalsProvider`, `MacroProvider`, `NewsProvider`,
`FilingsProvider`, `SentimentProvider`. Each maps to its ingestion table (§2 of the
synthesis): bars→`market_bars`, fundamentals→`fundamentals_quarterly`/`earnings_*`,
macro→`macro_series`, news→`news_sentiment`, filings→`insider_transactions`/`sec_filings`,
sentiment→`market_sentiment`.

### 2.3 `AnalysisEngine` — `backend/analysis/engine.py`

Exposes the synthesis §3.1 pipeline as composable stages. Inputs are pandas frames
of OHLCV bars; outputs are typed contracts.

```python
@runtime_checkable
class AnalysisEngine(Protocol):
    def compute_indicators(self, bars: Mapping[str, DataFrame], asof: datetime) -> list[IndicatorResult]: ...
    def score_symbol(self, symbol: str, bars: DataFrame, asof: datetime) -> SymbolScore: ...
    def rank_symbols(self, scores: list[SymbolScore]) -> list[RankedSymbol]: ...
```

`CompositeScorer` (`analysis/scoring/composite_scorer.py`) and `SymbolRanker`
(`analysis/scoring/symbol_ranker.py`) are **separate injectable Protocols** so the
Experiment Tracker can swap scorer versions (synthesis §6). `RiskManager`
(`trading/risk_manager.py`) is a Protocol; its `FixedFractionalRiskManager`
implementation (fixed-fractional sizing) is **filled in Phase 4** — see
`backend-services.md` §3/§4.

### 2.4 `Indicator` base — `backend/analysis/indicators/base.py`

```python
class Indicator(ABC):
    signal_id: str
    @abstractmethod
    def compute(self, df: DataFrame) -> Series: ...
```

Concrete indicators (filled after Phase 0) live under `analysis/signals/{technical,
fundamental,macro,sentiment}/` and return a normalized per-date `Series` the scorer
consumes; the base contract lives at `analysis/indicators/base.py` per the brief.

---

## 3. Data contracts

All in `backend/contracts.py`, Pydantic v2, `frozen=True`, `extra="forbid"`. The
**DB-column** column proves field-for-field alignment with `backend/db/models.py`.

| Contract | Maps to (table / source) | Key fields → DB columns |
|---|---|---|
| `OHLCVBar` | `market_bars` (`MarketBar`) | `symbol, ts, open, high, low, close, volume, adj_close` — exact |
| `IndicatorResult` | `signal_values` (`SignalValue`) | `symbol, ts, signal_id, value, data_completeness` — exact |
| `SymbolScore` | `algorithm_signals` (`AlgorithmSignal`) | `symbol, ts, score, action, reason, indicator_snapshot`; `data_completeness` is engine-local diagnostics |
| `RankedSymbol` | (ranker output, not persisted) | `rank: int`, `score: SymbolScore` |
| `Order` | `trade_orders` (`TradeOrder`) | `id, symbol, side, qty, price, commission, status, reason, strategy_version, ts` — exact (`id` optional pre-insert, DB `BIGSERIAL`; `commission` nullable, P10/migration `0009`) |
| `Position` | `portfolio_positions` (`PortfolioPosition`) | `symbol, qty, avg_cost, current_price, unrealized_pnl, updated_at` — exact |
| `AccountBalance` | assembled by `PortfolioManager` (not returned by the broker) | `cash, equity, total` — `total = broker.get_account_balance()`, `cash = broker.get_cash()`, `equity = total − cash` |
| `OrderStatus` | broker lifecycle (paper) | `order_id, status, filled_qty, avg_fill_price` |
| `PortfolioSnapshot` | `portfolio_nav` (`PortfolioNav`) | `ts, cash, equity, total, benchmark_value` — exact |
| `TradeRecord` | view over `trade_orders` | same as `Order` with non-optional `id` (dashboard reads filled rows) |
| `PerformanceMetrics` | `metrics.summarize_performance` output | `returns, risk, trades` (`dict[str, float]`) — mirrors the existing envelope |

**Decimal vs float:** money/prices/scores are `Decimal` end-to-end (matches the DB
`Numeric` columns — never float, per schema.md). `PerformanceMetrics` is the one
exception: it is `float` because `backend/analysis/performance/metrics.py` is
numpy/pandas-based and already returns floats; converting would lose nothing and add
friction. Enums (`OrderSide`, `OrderType`, `OrderState`, `SignalAction`) are
`StrEnum` so `.value` matches the free-string DB columns; the DB remains
authoritative on column width (e.g. `side String(8)`).

---

## 4. API contract

Single-user dashboard — **no auth** (CLAUDE.md). JSON only. Responses use the
`backend.contracts.*` / `api.schemas.*` models. The API is mostly read-only, but the
multi-portfolio + on-demand-run features (post-Phase-5) add a small set of writing
endpoints (portfolio CRUD, cash movements, watchlist edits, manual run). The list
below is **verified against the router source** in `backend/api/routers/`.

| Method · Path | Request | Response model |
|---|---|---|
| `GET /api/portfolio/summary` | `portfolio_id?` | `PortfolioSummary` |
| `GET /api/portfolio/positions` | `portfolio_id?` | `list[Position]` |
| `GET /api/portfolio/nav` | `portfolio_id?`, `start`, `end` | `list[PortfolioSnapshot]` |
| `GET /api/portfolio/performance` | `portfolio_id?`, `start`, `end` | `PerformanceMetrics` |
| `GET /api/portfolios` | — | `list[PortfolioSchema]` |
| `POST /api/portfolios` | `PortfolioCreate` (`name`, `initial_deposit`) | `PortfolioSchema` (201) |
| `PATCH /api/portfolios/{id}` | `PortfolioRename` (`name`) | `PortfolioSchema` |
| `DELETE /api/portfolios/{id}` | — | `{status, id}` (guards last portfolio) |
| `POST /api/portfolios/{id}/deposit` | `CashMovementCreate` (`amount`, `note?`) | `CashMovementSchema` (201) |
| `POST /api/portfolios/{id}/withdraw` | `CashMovementCreate` (`amount`, `note?`) | `CashMovementSchema` (201) |
| `GET /api/portfolios/{id}/movements` | `limit?` | `list[CashMovementSchema]` |
| `GET /api/market/quotes` | `symbols` (csv) | `list[QuoteEntry]` (live yfinance) |
| `GET /api/market/bars/{symbol}` | `start?`, `end?` | `list[OHLCVBar]` |
| `GET /api/market/watchlist` | — | `list[WatchlistEntry]` (+ latest price/score/action) |
| `POST /api/market/watchlist` | `WatchlistCreate` (`symbol`, `sector?`, `asset_class?`) | `WatchlistEntry` (201) |
| `DELETE /api/market/watchlist/{symbol}` | — | `WatchlistEntry` (soft-deactivate) |
| `GET /api/trades` | `portfolio_id?`, `symbol?`, `start?`, `end?`, `limit?` | `list[TradeRecord]` |
| `GET /api/trades/round-trips` | `portfolio_id?` | `list[TradeRoundTrip]` |
| `GET /api/algorithms/signals` | `asof?`, `limit?` | `list[SignalEntry]` |
| `GET /api/algorithms/accuracy` | — | `SignalAccuracySummary` (market-wide hit rate) |
| `GET /api/algorithms/experiments` | — | `list[ExperimentEntry]` |
| `POST /api/system/run` | — | `RunTrigger` (single-flight guarded) |
| `GET /api/system/status` | — | `SystemStatus` (per-job last/next run) |
| `GET /health` | — | `{"status":"ok"}` |

Router layout (real, `backend/api/routers/`): `portfolio.py` (summary, positions, nav,
performance), `portfolios.py` (CRUD + deposit/withdraw/movements), `market.py` (quotes,
bars, watchlist), `trades.py` (trades, round-trips), `algorithms.py` (signals, accuracy,
experiments), `system.py` (run, status). Routers take `AsyncSession` via a FastAPI
dependency yielding from `async_session` (`backend/db/session.py`). The active
portfolio is selected client-side via the optional `portfolio_id` query param
(`resolve_portfolio`); the `BrokerAdapter` seam is unaffected — `portfolio_id` is a
constructor arg to the broker, not part of `place_order` (CLAUDE.md multi-portfolio
note).

---

## 5. Configuration schema

Every value is an environment variable — no hardcoded values (CLAUDE.md). Strategy
weights/thresholds are **not** here; they live in `config/strategy.yaml` (synthesis
§3/§4) and are loaded by the engine. This table is infrastructure/runtime config.

| Env var | Type | Default | Description |
|---|---|---|---|
| `BROKER_ADAPTER` | str | `paper` | Selects the `BrokerAdapter` impl. Both `paper` and `mock_real` are registered in `broker_factory.py` (the env-only swap gate is satisfied); a real `alpaca` adapter is Phase 2. |
| `DATABASE_URL` | str | *(required)* | asyncpg URL, e.g. `postgresql+asyncpg://user:pass@db/trader`. Read by `db/session.py` (no default — fails fast). |
| `STRATEGY_CONFIG_PATH` | str | `config/strategy.yaml` | Path to the strategy weights/thresholds YAML the engine validates at startup. |
| `RISK_FREE_RATE` | float | `0.045` | Annual risk-free rate for Sharpe/Sortino/alpha (already read by `metrics.risk_free_rate_from_env`). |
| `STARTING_CASH` | Decimal | `500` | **Only** seeds the in-memory `MockRealBroker`'s starting cash. It does **not** drive the paper portfolio: paper cash is derived from the `cash_movements` ledger (`compute_cash`), so real budgets live in `cash_movements` (CLAUDE.md multi-portfolio note). |
| `SCHEDULER_TIMEZONE` | str | `UTC` | APScheduler timezone; daily jobs are specified in UTC (CLAUDE.md sequence). |
| `MISFIRE_GRACE_TIME` | int | `3600` | Seconds a missed job may still run (CLAUDE.md). |
| `API_HOST` | str | `0.0.0.0` | FastAPI bind host. |
| `API_PORT` | int | `8000` | FastAPI bind port. |
| `CORS_ALLOW_ORIGINS` | str (csv) | *(empty)* | Allowed origins; empty = same-origin only (SvelteKit served by FastAPI). |
| `OHLCV_PROVIDER` | str | `yfinance` | Primary OHLCV provider; `twelve_data` is the fallback behind the same Protocol. |
| `TWELVE_DATA_API_KEY` | str | *(empty)* | OHLCV fallback key (free tier). |
| `FRED_API_KEY` | str | *(empty)* | Macro series (FRED). Required to run `fetch_macro_data`. |
| `FINNHUB_API_KEY` | str | *(empty)* | News sentiment + consensus EPS / recommendations (free tier, 60/min). |
| `NEWSAPI_API_KEY` | str | *(empty)* | Optional secondary news source. |
| `ALPHA_VANTAGE_API_KEY` | str | *(empty)* | Optional news fallback (25 req/day — market-wide only). |
| `SEC_EDGAR_USER_AGENT` | str | *(empty)* | `name email` UA header EDGAR requires (Form 4 + 8-K); requests 403 without it. |
| `LOG_LEVEL` | str | `INFO` | Application log level. |

**Secrets:** every `*_API_KEY` and `DATABASE_URL` is a placeholder here — real values
go in `.env` (gitignored); `.env.example` carries placeholders only (CLAUDE.md /
Security Engineer gate). No real secret appears in this document.

---

## Handoff notes

**To the Backend Architect and Data Engineer.**

**What I produced**
- `backend/contracts.py` — all 11 inter-module DTOs (Pydantic v2, frozen), aligned 1:1 with `backend/db/models.py` columns.
- `backend/trading/broker_adapter.py` — `BrokerAdapter` Protocol (unchanged from CLAUDE.md) + re-exported `Order`/`Position`/`OrderStatus`.
- `backend/data_ingestion/protocols.py` — `MarketDataProvider` + `Fundamentals/Macro/News/Filings/Sentiment` sub-protocols, all async + batch.
- `backend/analysis/engine.py` — `AnalysisEngine` Protocol; `backend/analysis/indicators/base.py` — `Indicator` ABC.
- Stub Protocols: `analysis/scoring/composite_scorer.py`, `analysis/scoring/symbol_ranker.py`, `trading/risk_manager.py`.
- Package `__init__.py` files for `trading`, `data_ingestion[/providers]`, `analysis/indicators`, `analysis/scoring`, `analysis/signals/{technical,fundamental,macro,sentiment}`. This doc.

**What you need to know**
- **Data Engineer:** implement providers in `data_ingestion/providers/*` against the Protocols; return `backend.contracts` DTOs, then upsert via the natural keys in schema.md (`(symbol, ts)`, `(accession_no, txn_seq)`, …). Analysis never calls you — you write to the DB, analysis reads from it.
- **Backend Architect:** `PortfolioManager` depends on `BrokerAdapter` (the Protocol); inject `PaperBroker` by reading `BROKER_ADAPTER`. Wire API routers per §4 — every endpoint already has a query function; the FastAPI dependency yields from `async_session`. Keep `Decimal` end-to-end.
- All strategy weights/thresholds are `config/strategy.yaml`, not env and not code.

**Open questions / deferred**
1. **`market_sentiment` has no query function yet** (only `get_macro_regime_inputs` exists). `GET /api/market/sentiment` needs a `get_market_sentiment(session, asof)` added to `market_queries.py` — flagging for the Database Optimizer / Backend Architect.
2. **`Watchlist` DTO:** I did not add a `Watchlist` contract (it is config-like metadata, not inter-module flow). If the dashboard needs a typed response, add a small `WatchlistEntry` DTO in `contracts.py` mirroring the `watchlist` columns.
3. **`order_type` is on `place_order` but absent from the `trade_orders` table.** The DB does not persist order type (Phase 1 is market-only). Confirm whether to add the column or keep it transient.
4. **`pydantic` and `pandas` are not yet in the active environment** (`.venv-db` is DB-only). DevOps must add `pydantic>=2`, `pandas`, `fastapi`, `apscheduler` to the API/scheduler image requirements; files compile but won't import until then.

---

## Update notes

**2026-06-02** — reconciled this doc with the real code (verified against the sources cited):
- **§2.1 `BrokerAdapter`** — corrected to the real **`async` + `qty: Decimal`** shape and added the **`async get_cash() -> Decimal`** method; explained the `get_cash` rationale (PortfolioManager builds `AccountBalance` from broker calls only, keeping the in-memory `MockRealBroker` self-consistent). CLAUDE.md already blesses async+Decimal.
- **§2.3 / dependency rules** — `trading/risk_manager.py` is **implemented in Phase 4** (`FixedFractionalRiskManager`, fixed-fractional sizing), not a stub.
- **§3** — `AccountBalance` is **assembled by PortfolioManager** (`total = get_account_balance()`, `cash = get_cash()`, `equity = total − cash`), not returned by the broker.
- **§4** — replaced the stale endpoint table with the real routers (`portfolio`, `portfolios`, `market`, `trades`, `algorithms`, `system`), including portfolio CRUD + deposit/withdraw/movements, `system/run`+`status`, `market/quotes`, `trades/round-trips`, `algorithms/accuracy`.
- **§5** — `BROKER_ADAPTER`: `mock_real` is **registered** in `broker_factory.py` (env-only swap gate satisfied). `STARTING_CASH` only seeds `MockRealBroker`; paper cash is `cash_movements`-derived (`compute_cash`).
