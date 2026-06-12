# Autonomous Trader — Project Directives

This file is the **constitution of the project**. Every agent working on this codebase must read it before doing anything. Rules here override individual agent defaults.

---

## What this project is

An autonomous paper-trading system that:
- Fetches daily market data (stocks, ETFs, indexes) and a wide range of predictive signals
- **Predicts market movements** using multi-factor analysis: technical, fundamental, macro, sentiment, news, and smart-money signals combined into a composite score
- Scores and ranks assets and acts ahead of expected moves — not after them
- Simulates trades in a virtual portfolio (no real money)
- Exposes a web dashboard to monitor everything
- Runs on a Raspberry Pi 4 via Docker Compose (ARM64, 4GB RAM)
- Is designed so that swapping paper trading for real broker calls requires only one environment variable change

**Phase 1 (current):** Simulation only. No real trading. No real money.
**Phase 2 (future):** Real broker integration via the BrokerAdapter seam.

---

## Approved architecture

```
docker-compose (ARM64)
├── db         → PostgreSQL 16 + TimescaleDB
├── api        → FastAPI + SvelteKit static build (single container)
└── scheduler  → APScheduler with PostgreSQL job store
```

- `api` and `scheduler` share the same Python codebase but have different entrypoints
- Services communicate **exclusively through the database** — no RPC, no message queues, no shared memory
- SvelteKit is built as static files and served by FastAPI via `StaticFiles` — no separate Nginx container

---

## The BrokerAdapter seam — sacred rule

This is the most critical architectural decision. It must never be violated.

```python
class BrokerAdapter(Protocol):
    def place_order(self, symbol: str, side: str, qty: Decimal, order_type: str) -> Order: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_balance(self) -> Decimal: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
```

> **`qty` is `Decimal`, not `int`** — the seam supports fractional shares so a small budget can
> still take a position in a high-priced symbol. Every adapter (PaperBroker, MockRealBroker, a
> future real one) honours it; the type is consistent across the whole seam, so this is not a bypass.

- `PortfolioManager` calls `BrokerAdapter` — never a concrete broker directly
- `PaperBroker` is the only implementation in Phase 1
- Switching to real trading = changing `BROKER_ADAPTER=paper` to `BROKER_ADAPTER=alpaca` in `.env`
- No other code changes allowed for the swap

**Any agent that bypasses this protocol will have their work rejected by the Reality Checker.**

---

## What is intentionally undefined

These modules have their **interfaces defined** but no business logic yet. They will be filled after the Phase 0 research is complete. Every agent must leave them as clean stubs:

- `analysis/signals/technical/` — which technical indicators and thresholds to use
- `analysis/signals/fundamental/` — which fundamental ratios and scoring logic
- `analysis/signals/macro/` — which macro indicators and regime detection logic
- `analysis/signals/sentiment/` — which sentiment sources and normalization approach
- `analysis/scoring/` — how to weight all signal categories into a composite score
- `trading/risk_manager.py` — position sizing rules (leave configurable %, no hardcoded values)
- `watchlist` table — which symbols/sectors to track (leave empty, populated at runtime)

**All signal weights, thresholds, and parameters must be configurable via `config/strategy.yaml` — never hardcoded.**

### Future: multi-market by capital (not yet built)

The current sizing model is single-universe fractional-share investing: any budget participates,
breadth scales with `MAX_OPEN_POSITIONS` and the watchlist. A richer model — selecting *different
markets* with their own minimum-investment rules based on available capital (small budget → venues
allowing tiny tickets; larger budget → more markets) — is **deliberately out of scope for Phase 1**
and would extend the `RiskManager` / universe model. Documented here so it is a planned seam, not an
accidental omission.

---

## Agent roster and responsibilities

### Phase 0 — Research (before any code)

Three parallel research streams, then one synthesis step. **Nothing else starts until the synthesis document exists.**

#### Phase 0A — Three streams in parallel ⚡

| Agent | Stream | Responsibility | Output |
|---|---|---|---|
| **Investment Researcher** | Technical + Fundamental | Sector universe, technical signals (momentum, mean reversion, volume), fundamental company signals (earnings, revenue, margins, valuation ratios, earnings surprises, analyst revisions) | `docs/research/01-technical-fundamental.md` |
| **Trend Researcher** | News + Sentiment + Smart Money | How news events move prices, sentiment data sources (Reddit, StockTwits, put/call ratio, Fear & Greed), smart money signals (unusual options flow, insider Form 4 filings, dark pool volume, 13F changes), alternative data (SEC 8-K filings, job postings as growth proxy) | `docs/research/02-news-sentiment-smartmoney.md` |
| **Financial Analyst** | Macro + Intermarket + Calendar | Macro regime signals (yield curve, CPI/PPI, leading economic indicators), intermarket relationships (bonds/stocks/commodities/FX), sector rotation model (economic cycle phases → defensive vs cyclical), calendar effects (earnings seasons, FOMC weeks, OpEx cycles, seasonal patterns), market breadth signals | `docs/research/03-macro-intermarket-calendar.md` |

#### Phase 0B — Synthesis (after all three streams) →

| Agent | Responsibility | Output |
|---|---|---|
| **Investment Researcher** | Read all three research docs and produce a unified signal priority map: which signals to implement first, what data sources are needed, what database tables are required, what prediction horizon each signal targets | `docs/research/00-signal-synthesis.md` — the master document that ALL Phase 1+ agents must read |

### Phase 1 — Foundation (parallel)

| Agent | Responsibility | Output |
|---|---|---|
| **Software Architect** | Module dependency graph, all Protocol definitions (`BrokerAdapter`, `MarketDataProvider`, `AnalysisEngine`), internal API contracts | `docs/architecture/module-contracts.md` + all Protocol files in `backend/` |
| **Database Optimizer** | Full TimescaleDB schema, hypertable config, compression, continuous aggregates, indexes | `backend/db/migrations/` (Alembic files) + `docs/architecture/schema.md` |
| **Workflow Architect** | Complete workflow tree: happy paths, failure modes, recovery paths, daily job sequence, what happens if yfinance fails, if scheduler crashes mid-job | `docs/architecture/workflow-tree.md` |

### Phase 2 — Financial domain (parallel, uses Phase 0 output)

| Agent | Responsibility | Output |
|---|---|---|
| **Financial Analyst** | Define portfolio performance metrics: Sharpe ratio, max drawdown, CAGR, alpha vs benchmark, calmar ratio. Define how these are computed and stored. | `docs/finance/performance-metrics.md` + metric computation functions in `backend/analysis/performance/` |
| **FP&A Analyst** | Define P&L reporting structure, period-over-period comparisons, what constitutes a "good" simulation run, how to present results | `docs/finance/reporting-structure.md` |
| **Experiment Tracker** | Design the framework to compare algorithms: how to record which strategy was active, how to A/B test scorer versions, how to measure if a parameter change improves results | `docs/finance/experiment-framework.md` + `backend/experiments/` module skeleton |

### Phase 3 — Design (parallel, uses Phase 0+2 output)

| Agent | Responsibility | Output |
|---|---|---|
| **UI Designer** | Visual system for the dashboard: color tokens (financial red/green conventions), typography, dark theme, component specs, chart visual language | `docs/design/ui-system.md` + `frontend/src/lib/styles/` |
| **UX Architect** | Information architecture: main page layout, navigation structure, data hierarchy, what goes above the fold, interaction patterns | `docs/design/ux-architecture.md` + `frontend/src/routes/` skeleton |

### Phase 4 — Backend implementation (sequential)

| Agent | Responsibility | Output | Depends on |
|---|---|---|---|
| **Data Engineer** | `MarketDataProvider` protocol implementation, yfinance + Twelve Data adapters, data validation, idempotent upsert for `market_bars` | `backend/data_ingestion/` | Phase 1 (Software Architect contracts) |
| **Backend Architect** | FastAPI routers, APScheduler jobs, `PortfolioManager`, `PaperBroker`, dependency injection for `BrokerAdapter` | `backend/api/`, `backend/trading/`, `backend/scheduler/` | Data Engineer output |
| **AI Engineer** | Analysis engine structure: base `Indicator` class, 3 placeholder indicators, `CompositeScorer` with configurable weights, `SymbolRanker` | `backend/analysis/` | Backend Architect output + Financial Analyst metrics |

### Phase 5 — Frontend + Infrastructure (parallel)

| Agent | Responsibility | Output | Depends on |
|---|---|---|---|
| **Frontend Developer** | SvelteKit dashboard: portfolio summary, NAV chart, candlestick chart, trades table, algorithm signals, market overview | `frontend/` | UX Architect skeleton + UI Designer system + Backend Architect API routes |
| **DevOps Automator** | Multi-stage Dockerfile, `docker-compose.yml`, ARM64 images, health checks, volume mounts, startup ordering | `docker/`, `.env.example` | Backend Architect (knows all services) |

### Phase 6 — Quality gates (sequential)

| Agent | Responsibility | Output | Depends on |
|---|---|---|---|
| **Analytics Reporter** | Validate dashboard shows correct metrics, define KPI completeness checklist, verify data flows from scheduler → DB → API → UI | `docs/qa/analytics-checklist.md` | Phase 5 complete |
| **Security Engineer** | Audit secrets management, API input validation, CORS, SQL injection prevention, `.env.example` hygiene | `docs/qa/security-audit.md` + fixes applied directly | Phase 5 complete |
| **Reality Checker** | Final gate: can `docker compose up` start cleanly? Do all 3 daily jobs run? Does BrokerAdapter swap work with env var only? Is idle RAM < 1GB? | Pass/fail checklist | All previous phases |

---

## Agent dependency map

```
[Phase 0A: parallel] ─────────────────────────────────────────────
Investment Researcher (Technical+Fundamental) ──┐
Trend Researcher (News+Sentiment+SmartMoney)  ──┤──► Phase 0B
Financial Analyst (Macro+Intermarket+Calendar)──┘

[Phase 0B: synthesis] ────────────────────────────────────────────
Investment Researcher reads all 3 → docs/research/00-signal-synthesis.md
        │
        ▼
[Phase 1: parallel] ──────────────────────────────────────────────
Software Architect ──┐
Database Optimizer ──┤──► [all Phase 2+ agents need these outputs]
Workflow Architect ──┘

[Phase 2: parallel, needs Phase 0] ───────────────────────────────
Financial Analyst ──┐
FP&A Analyst ───────┤──► [AI Engineer needs these outputs]
Experiment Tracker ─┘

[Phase 3: parallel, needs Phase 0+2] ─────────────────────────────
UI Designer ────────┐
UX Architect ───────┘──► [Frontend Developer needs these outputs]

[Phase 4: sequential] ────────────────────────────────────────────
Data Engineer → Backend Architect → AI Engineer

[Phase 5: parallel, needs Phase 3+4] ─────────────────────────────
Frontend Developer ─┐
DevOps Automator ───┘

[Phase 6: sequential] ────────────────────────────────────────────
Analytics Reporter → Security Engineer → Reality Checker
```

---

## Universal rules — every agent must follow these

### Output format
- Every agent deposits outputs into `docs/` or their assigned `backend/`/`frontend/` path
- Docs use Markdown. Code follows the stack conventions below.
- Each agent's output document must start with: `<!-- Agent: [AgentName] | Phase: [N] | Depends on: [list] -->`

### Code conventions
- Python 3.12, type hints everywhere, no `Any` unless unavoidable
- SQLAlchemy 2.x async style (`async_sessionmaker`, `AsyncSession`)
- All configuration via environment variables — no hardcoded values
- No comments explaining WHAT the code does — only WHY if non-obvious
- No docstring novels — one short line max

### ARM64 constraint
- Every Docker image must have a verified ARM64 build
- No x86-only images. If unsure, check Docker Hub manifest before using.
- `timescale/timescaledb:latest-pg16` — verified ARM64
- `python:3.12-slim` — verified ARM64
- `node:20-alpine` — verified ARM64

### What agents must NOT do
- Implement real broker API calls (Phase 2 work, out of scope now)
- Hardcode watchlist symbols — the watchlist is populated at runtime
- Hardcode algorithm weights or thresholds — all configurable via env/config
- Bypass `BrokerAdapter` — `PortfolioManager` never touches a broker directly
- Create auth/multi-user functionality — single-user dashboard
- Add features beyond what their phase requires

### Handoff protocol
When an agent completes their phase, they must append a `## Handoff notes` section at the end of their output document listing:
- What they produced
- What the next agent needs to know
- Any open questions or decisions they deferred

---

## Directory structure (target)

```
autonomous-trader/
├── CLAUDE.md                          ← this file
├── LAUNCH_PROMPT.md                   ← prompt to start development
├── .env.example
├── docs/
│   ├── research/
│   │   ├── 00-signal-synthesis.md     ← Investment Researcher (Phase 0B synthesis — READ THIS FIRST)
│   │   ├── 01-technical-fundamental.md← Investment Researcher (Phase 0A)
│   │   ├── 02-news-sentiment-smartmoney.md ← Trend Researcher (Phase 0A)
│   │   └── 03-macro-intermarket-calendar.md← Financial Analyst (Phase 0A)
│   ├── architecture/
│   │   ├── module-contracts.md        ← Software Architect
│   │   ├── schema.md                  ← Database Optimizer
│   │   ├── workflow-tree.md           ← Workflow Architect
│   │   ├── data-ingestion.md          ← Data Engineer (Phase 4)
│   │   ├── analysis-engine.md         ← AI Engineer (Phase 4)
│   │   └── backend-services.md        ← Backend Architect (Phase 4)
│   ├── finance/
│   │   ├── performance-metrics.md     ← Financial Analyst
│   │   ├── reporting-structure.md     ← FP&A Analyst
│   │   └── experiment-framework.md    ← Experiment Tracker
│   ├── design/
│   │   ├── ui-system.md               ← UI Designer
│   │   └── ux-architecture.md         ← UX Architect
│   └── qa/
│       ├── analytics-checklist.md     ← Analytics Reporter
│       └── security-audit.md          ← Security Engineer
├── backend/
│   ├── api/
│   │   ├── main.py
│   │   └── routers/
│   │       ├── portfolio.py
│   │       ├── market.py
│   │       ├── trades.py
│   │       └── algorithms.py
│   ├── data_ingestion/
│   │   ├── protocols.py               ← all data provider Protocols
│   │   └── providers/
│   │       ├── ohlcv/
│   │       │   ├── yfinance_provider.py
│   │       │   └── twelve_data_provider.py
│   │       ├── fundamental/
│   │       │   └── yfinance_fundamentals.py
│   │       ├── macro/
│   │       │   └── fred_provider.py
│   │       ├── news/
│   │       │   └── newsapi_provider.py
│   │       └── sentiment/
│   │           └── alternative_me_provider.py
│   ├── analysis/
│   │   ├── signals/
│   │   │   ├── technical/             ← stubs only (filled after Phase 0)
│   │   │   ├── fundamental/           ← stubs only (filled after Phase 0)
│   │   │   ├── macro/                 ← stubs only (filled after Phase 0)
│   │   │   └── sentiment/             ← stubs only (filled after Phase 0)
│   │   ├── scoring/                   ← CompositeScorer, SymbolRanker (stubs)
│   │   ├── performance/               ← Financial Analyst metrics
│   │   └── engine.py                  ← AnalysisEngine Protocol
│   ├── trading/
│   │   ├── broker_adapter.py          ← BrokerAdapter Protocol (sacred)
│   │   ├── paper_broker.py
│   │   ├── portfolio_manager.py
│   │   └── risk_manager.py
│   ├── experiments/                   ← Experiment Tracker skeleton
│   ├── scheduler/
│   │   ├── jobs.py
│   │   └── main.py
│   └── db/
│       ├── models.py
│       ├── queries/
│       │   ├── market_queries.py
│       │   └── portfolio_queries.py
│       └── migrations/                ← Alembic
├── frontend/
│   └── src/
│       ├── lib/
│       │   └── styles/                ← UI Designer tokens
│       └── routes/
│           ├── +page.svelte           ← main dashboard
│           ├── portfolio/
│           ├── market/
│           └── history/
└── docker/
    ├── Dockerfile
    └── docker-compose.yml
```

---

## Performance budget (Raspberry Pi 4, 4GB RAM)

| Service | Idle RAM target |
|---|---|
| TimescaleDB | < 200 MB |
| API (FastAPI) | < 120 MB |
| Scheduler | < 100 MB (peak ~400 MB during analysis) |
| OS + Docker overhead | ~400 MB |
| **Total idle** | **< 820 MB** |
| **Total peak** | **< 1.2 GB** |

Any agent whose implementation would exceed these budgets must flag it in their handoff notes.

---

## Data sources by signal category

The exact sources to use are determined by Phase 0 research. This table is the expected outcome:

| Category | Source | API Key | Cost |
|---|---|---|---|
| OHLCV (primary) | `yfinance` | No | Free |
| OHLCV (fallback) | Twelve Data | Yes | Free tier |
| Fundamentals (EPS, P/E, revenue) | `yfinance` financials | No | Free |
| Earnings calendar + surprises | `yfinance` / Nasdaq API | No | Free |
| Analyst ratings + revisions | `yfinance` | No | Free |
| Insider transactions | OpenInsider (scrape) / SEC EDGAR | No | Free |
| SEC filings (8-K, 10-K, 10-Q) | SEC EDGAR full-text API | No | Free |
| Macro indicators (rates, CPI, GDP) | FRED API (Federal Reserve) | Yes | Free |
| News headlines + sentiment | NewsAPI / Alpha Vantage News | Yes | Free tier |
| Market sentiment (Fear & Greed) | Alternative.me API | No | Free |
| Put/call ratio + VIX | CBOE via `yfinance` | No | Free |
| Options unusual activity | Unusual Whales / Barchart | Yes | Paid (Phase 2) |
| Market breadth | `yfinance` (SPY breadth ETFs) | No | Free |

**Phase 0 research must confirm or replace these sources.** All providers implement a typed Protocol — swapping sources never touches analysis logic.

---

## Daily job sequence (scheduler)

```
06:00 UTC  →  fetch_macro_data()          ← FRED API: rates, inflation, leading indicators
06:15 UTC  →  fetch_news_sentiment()      ← NewsAPI + Alternative.me Fear & Greed
06:30 UTC  →  fetch_market_data()         ← OHLCV bars (yfinance primary)
06:45 UTC  →  fetch_fundamentals()        ← Earnings, analyst revisions, insider filings
07:30 UTC  →  run_analysis()              ← All signal categories → composite score
08:00 UTC  →  execute_paper_trades()      ← Top-ranked signals → simulated orders
08:15 UTC  →  update_portfolio_nav()      ← Snapshot portfolio value
```

> **Implementation status.** The Reality Checker still gates on the original 4-job
> subset (`fetch_market_data → run_analysis → execute_paper_trades → update_portfolio_nav`,
> 06:30/07:30/08:00/08:15 UTC). **Post-Phase-5, the three remaining ingestion jobs are now
> built** and the full 7-job sequence runs: `fetch_macro_data` (06:00, FRED →
> `macro_series`), `fetch_news_sentiment` (06:15, Finnhub `/company-news` → `news_sentiment`
> article counts) and `fetch_fundamentals` (06:45, Finnhub `/stock/financials-reported` →
> `fundamentals_quarterly`). Each is market-day-gated, idempotent, and **skips cleanly
> when its provider key is absent** (`FRED_API_KEY` / `FINNHUB_API_KEY`), so the pipeline
> degrades rather than fails. `run_analysis` still **trades on technical indicators only**
> (RSI/MA/ATR): the new macro/fundamental/sentiment signals are computed and persisted to
> `signal_values` in **observation mode** (`macro_regime`, `revenue_accel`, `earnings_accel`,
> `quality`, `news_buzz`) but are **not** fed to the composite scorer — they change no trade
> until a deliberate **activation** (adding weights / a regime multiplier in `strategy.yaml`,
> gated by the Experiment Tracker). Full detail: `docs/architecture/data-ingestion.md`.

> **Post-Phase-5 additions.** The 4-job pipeline can also be launched **on demand**:
> `POST /api/system/run` runs the same sequence in order (single-flight guarded in the API
> process; cross-process safety relies on the existing per-job idempotency), surfaced as a
> **Run now** button on the dashboard. The `watchlist` is seeded at runtime via
> `POST /api/market/watchlist` / `DELETE /api/market/watchlist/{symbol}` (and a small Market-page
> control) — still never hardcoded. Position sizing supports **fractional shares**
> (`ALLOW_FRACTIONAL`, `MIN_POSITION_EUR`) so a small budget actually trades.

> **Default watchlist seed (owner-approved).** So the system trades out of the box, a
> committed data file `config/watchlist.seed.csv` (a diversified, liquid yfinance-compatible
> basket) is loaded by `init-db.sh` via `python -m backend.db.seed_watchlist` **only when the
> `watchlist` table is empty** — removed symbols are never resurrected. This does **not** hardcode
> symbols in analysis logic: they live as editable data and the API remains the source of truth.
> Point `WATCHLIST_SEED_FILE` elsewhere to use a different basket, or set it empty to disable.

> **Multi-portfolio (post-Phase-5).** The system holds several first-class **portfolios**
> (`portfolios` table), each with its own budget, positions, trades and NAV. `trade_orders`,
> `portfolio_positions` and `portfolio_nav` are scoped by `portfolio_id` (the last two re-keyed
> to composite PKs; `portfolio_nav`'s continuous aggregate is recreated grouped by
> `portfolio_id`). Budgets are **editable** via `cash_movements` (deposits/withdrawals); cash =
> Σdeposits − Σwithdrawals − Σbuys + Σsells, and performance is measured against **net
> contributed capital**, not a fixed starting figure. Migration `0005` seeds two portfolios
> (`Cartera 500` = 500 €, `Cartera 100K` = 100 000 €); more can be created/deleted at runtime.
> The daily engine and **Run now** trade **every active portfolio**, each sized by its own cash,
> with a per-portfolio idempotency guard. The frontend selects the active portfolio client-side
> (`?portfolio_id=`); the **`BrokerAdapter` seam is unchanged** — `portfolio_id` is a constructor
> argument to `PaperBroker`/`MockRealBroker`, not part of `place_order`. `STARTING_CASH` no longer
> drives the paper portfolio (it only seeds the `mock_real` double's in-memory cash); real budgets
> live in `cash_movements`.

> **Intraday protective sell (post-Phase-5).** Beyond the daily jobs above there is a fifth,
> **interval** job — `protective_sell` — that runs every `PROTECTIVE_SELL_INTERVAL_MIN` (15 min)
> **only during market hours** and sells held positions on a **trailing stop** from a per-position
> `high_water_mark` (migration `0006`). Stop distance is `ATR(14)×STOP_ATR_MULTIPLE` (fallback
> `TRAILING_STOP_PCT`), tightened/held by a live-VIX regime. It is **not** in `JOB_SCHEDULE` (which
> the API shares for next-run times) — it's registered as an `IntervalTrigger` in
> `scheduler/main.py`, gated by `PROTECTIVE_SELL_ENABLED`. Maths in `backend/trading/stops.py`;
> the `BrokerAdapter` seam is unchanged (sells via `place_order`). Full design:
> `docs/architecture/protective-sell.md`.

> **Per-portfolio strategy version — A/B testing (post-Phase-5).** Each portfolio carries an
> editable `strategy_label` (`portfolios.strategy_label`, migration `0008`; set via
> `PATCH /api/portfolios/{id}` / the Portfolios admin), so different portfolios can run
> **different strategy versions at once** and be compared. A version is a named overlay file
> `config/strategies/<label>.yaml` **deep-merged onto `config/strategy.yaml`** (the base); a
> label whose overlay is empty equals the base. `load_strategy_config(label=...)` /
> `list_strategy_versions()` resolve them (`backend/analysis/config.py`); `GET /api/strategies`
> lists them. The daily `run_analysis` still persists ONE base signal set; **`execute_paper_trades`
> scores each distinct version once and trades every portfolio under its own config**, tagging
> `trade_orders.strategy_version`; `protective_sell` resolves stop params per portfolio. v1 vs v2
> is compared by **portfolio** performance (NAV/P&L/alpha) — no schema change to the signal tables.
> **Still nothing hardcoded**: every weight/threshold lives in the (versioned) `StrategyConfig`,
> and the new `trading` section (`StrategyConfig.trading`) is **all-optional with `None` defaults
> that fall back to the existing env/defaults**, so the base config leaves execution byte-for-byte
> unchanged and an overlay only changes what it sets. The `BrokerAdapter` seam is untouched
> (`config` is a constructor arg to `PortfolioManager`, never part of `place_order`). Shipped
> variants: `v1` = base (control), `v2` = the loss-diagnosis fixes (ATR out of the score, RSI
> mean-reversion, ma_trend cap, re-entry cooldown, stop-distance floor, no pyramiding), **`v3` =
> v2 + P7 (cross-sectional rank-normalization)**. The frontend
> **`/compare`** route overlays each portfolio's NAV (% rebased or € absolute) with a shared crosshair
> tooltip to compare versions. Diagnosis and rationale: `docs/diagnostics/01-diagnostico-perdidas.md`,
> `02-plan-mejora.md`, `03-plan-v3.md`.

> **v3 — P7 / P10 / P12 (post-Phase-5).** v3 layers three diagnostics fixes onto v2.
> **P7 (rank-normalization, per-version):** when `scoring.rank_normalize: true` (a new
> `ScoringConfig` field, off in base/v1/v2), each weighted sub-score is replaced by its
> **percentile rank across the day's universe** before weighting, so the 60/45 buy/exit gate is
> *relative* to the universe, not an absolute biased threshold. The normalization lives one layer
> above the per-symbol scorer in `engine.score_universe`, which both `run_analysis` and
> `execute_paper_trades` now call (single universe pass → no divergence; base persists the raw
> set). **P10 (commissions, GLOBAL not per-version):** `PaperBroker` charges
> `COMMISSION_PCT × notional + COMMISSION_PER_ORDER` (env, default 0) on every filled order, stored
> in a new nullable `trade_orders.commission` (migration `0009`) and subtracted by `compute_cash`
> — it drags **cash/NAV but not contributed capital**, so the A/B is fairly penalized for churn;
> every version pays the same (a market reality). **P12 (data-freshness gate, GLOBAL):**
> `MAX_BAR_STALENESS_DAYS` (env sessions, default 0 = off) excludes a symbol from
> scoring/execution when its latest bar is too many sessions stale. Seam untouched (commission is
> a `PaperBroker` detail; `qty` stays `Decimal`); nothing hardcoded. **P11** (momentum +
> macro multiplier) stays out of scope — a future v4. Live portfolios `v3-500` / `v3-100k` run it.
> Full plan/measurement: `docs/diagnostics/03-plan-v3.md`.

> **v4 — momentum cross-seccional (P11 fase 1).** v4 = v3 + a `PriceMomentum` indicator
> (`signal_id="momentum"`: return over `period=126` bars ending `skip=21` bars ago, logistic
> squash). Its **params live in the base** `strategy.yaml` so every version computes and
> `run_analysis` persists it in **observation mode**; only `config/strategies/v4.yaml` gives it
> **weight** (0.40). With `rank_normalize` (inherited from v3) the sub-score is the symbol's
> momentum **percentile across the day's universe** — relative momentum (synthesis §3.1). P11
> phase 2 (macro regime multiplier) is deliberately deferred to a future v5 — one variable per
> experiment. Live data findings + the broker fixes shipped alongside (stale `high_water_mark` on
> re-entry causing stop churn, `MIN_CASH_PCT` reserve not held, unfunded buys accepted, zero-coverage
> SELL, stale-analysis gate): `docs/diagnostics/04-plan-v4.md`. **v2 never trades** (composite ≈49
> vs absolute gate 60 — anticipated in 03-plan-v3.md): kept active only as a cash-like baseline.

> A user-facing plain-language explanation of the versions and their differences lives on the
> dashboard **`/info`** page (`frontend/src/routes/info`, i18n keys `info.versions.*`).

**Data ingestion jobs (06:xx) run in sequence** — each writes to DB before next starts.
**Analysis (07:30) reads all categories** from DB — never calls external APIs directly.
All jobs are idempotent. Running twice on the same day must not create duplicate data.
All jobs: `misfire_grace_time=3600` — if missed, run within 1 hour or skip.

---

## Production deployment & auto-deploy (post-Phase-5)

- **The live stack is the PRODUCTION compose** (`docker/docker-compose.yml` only, no dev
  override): FastAPI serves the baked SvelteKit build and owns host port **8030** (`API_PORT=8030`
  in `.env`; db 8031, scheduler 8032). There is no Vite container in production — the dev
  override (`docker-compose.dev.yml`, Vite on 8030, FastAPI moved to 8033) is opt-in for
  development sessions only.
- **Auto-deploy on merge.** `.github/workflows/deploy.yml` targets the **self-hosted runner on
  the Pi** (systemd service `actions.runner.…pi-trader`): every push/merge to `main` runs
  `scripts/deploy.sh`, which fetches `origin/main`, **rebuilds the image** (source + frontend are
  baked in — every change needs a rebuild), `up -d --remove-orphans` (init re-runs migrations),
  health-checks `/api/health` and **rolls back to the previously deployed commit on any failure**.
  CI (ci.yml, GitHub-hosted) is the test gate; deploy.sh runs no tests. A **cron fallback**
  (`crontab -l`, every 15 min, logs to `~/.local/state/autonomous-trader/deploy.log`) covers
  runner outages; it dedupes against the last deployed SHA (`~/.local/state/autonomous-trader/
  deployed-sha`) and **refuses to deploy over a dirty working tree**, so local work is never wiped.
- Direct pushes to `main` are blocked by the pre-push hook (`make install-hooks`) — changes land
  via PR; the merge triggers the deploy with no manual step.

---

## Local development & testing (post-Phase-5)

- **Hot reload / bind mounts.** `docker/docker-compose.dev.yml` bind-mounts the repo (`..:/app`)
  into `api`, `init`, `scheduler` and `frontend`, so code edits take effect **without an image
  rebuild**. Only `api` (uvicorn `--reload`) and `frontend` (vite HMR) reload automatically — the
  **`scheduler` has no reload**, so after changing `backend/scheduler/*`, job code or a migration
  you must `docker restart trader-scheduler`. Apply migrations from the `trader-api` container
  (it has the live code): `docker exec trader-api sh -lc "cd backend/db/migrations && alembic upgrade head"`.
  `docker/init-db.sh` must keep its execute bit (`chmod +x`).
- **Tests.** A pytest suite lives under `backend/tests/` (unit / integration / regression) and runs
  **in a throwaway container from the app image with the working tree bind-mounted**
  (`scripts/test.sh` — the live `trader-api` is the production container with baked code, so
  exec-ing into it would test the deploy, not your edits) against a separate database
  `autonomous_trader_test`:
  `make test` (full), `make test-unit` (fast, no DB), `make lint`, `make typecheck`. Test-only deps
  are in `backend/requirements-dev.txt` (not baked into the image). No test touches the real network
  (provider HTTP is mocked with `respx`). Full strategy: `docs/qa/testing-strategy.md`.

---

## Reality Checker checklist (final gate)

The project is not complete until all of these pass:

- [ ] `docker compose up` starts all 3 services cleanly on ARM64
- [ ] TimescaleDB hypertables are created on first startup
- [ ] Scheduler runs all 4 daily jobs in sequence without errors
- [ ] API returns valid JSON for all documented endpoints
- [ ] Frontend loads, connects to API, and renders at least one chart
- [ ] Swapping `BROKER_ADAPTER=paper` → `BROKER_ADAPTER=mock_real` requires zero code changes
- [ ] Idle RAM total < 820 MB measured with `docker stats`
- [ ] No real API keys committed in any file
- [ ] `.env.example` contains only placeholder values, never real secrets
- [ ] All analysis/scoring modules are stubs with clean interfaces, not hardcoded logic
