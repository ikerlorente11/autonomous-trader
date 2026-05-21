# Autonomous Trader — Development Launch Prompt

Copy and paste each phase prompt into Claude Code when the previous phase is complete.
Agents that can run in parallel are marked with ⚡. Sequential agents are marked with →.

Read `CLAUDE.md` before launching any phase. All agents must follow those directives.

---

## PHASE 0 — Research
*Run this first. Nothing else starts until this output exists.*

```
Activate Investment Researcher.

Read the file CLAUDE.md in the current project directory and follow all directives in it.

Your mission: produce a deep research document at docs/research/sector-study.md

The project is an autonomous paper-trading simulator. The algorithm and scoring logic
have NOT been defined yet — that is exactly what you need to research. We need to know
where to invest before we decide how to invest.

Deliver a structured document covering:

1. SECTOR UNIVERSE
   Research and evaluate which market sectors and asset classes are best suited for
   algorithmic trading with daily timeframes. Cover at minimum:
   - US equities by sector (Technology, Healthcare, Energy, Finance, Consumer, etc.)
   - ETFs (sector ETFs, factor ETFs, index ETFs)
   - Consider: liquidity requirements, volatility profiles, correlation between sectors

2. SIGNAL TAXONOMY
   What types of financial signals and indicators have proven value for daily timeframe
   algorithmic strategies? Research and classify:
   - Trend signals (which moving averages, which timeframes actually matter)
   - Momentum signals (RSI, MACD, Rate of Change — which thresholds are meaningful)
   - Volatility signals (ATR, Bollinger Bands — how to use them for position sizing)
   - Volume signals (OBV, VWAP — what they tell you on daily bars)
   - Mean reversion vs momentum: which works better for which asset class?

3. SCORING FRAMEWORK PROPOSAL
   Based on your research, propose a composite scoring approach:
   - How to combine multiple signals into a single score (0-100 scale)
   - Which signals to weight more heavily and why
   - How to normalize signals across different asset classes
   - How to avoid overfitting a scoring model to historical data

4. BENCHMARK STRATEGY
   Define a simple benchmark strategy the simulation should compare itself against
   (e.g., buy-and-hold S&P 500). This is how we measure if the algorithm adds value.

5. WATCHLIST SEED
   Provide an initial watchlist of 30-50 symbols across the recommended sectors.
   For each symbol include: ticker, sector, asset class, why it was selected.

6. RISK CONSIDERATIONS
   What are the main risks of automated daily trading that the simulation must model
   correctly? (slippage, bid-ask spread estimates, market impact, overnight risk)

Output: docs/research/sector-study.md

End with a ## Handoff notes section listing key decisions made and any open questions
for the Financial Analyst and AI Engineer.
```

---

## PHASE 1 — Foundation
*Run all three in parallel ⚡ after Phase 0 is complete.*

### ⚡ Software Architect

```
Activate Software Architect.

Read CLAUDE.md first. Follow all directives.

Context: Phase 0 (Investment Researcher) has completed. Read docs/research/sector-study.md
for domain context before designing.

Your mission: define the complete module contract layer for the autonomous-trader project.

Produce docs/architecture/module-contracts.md covering:

1. MODULE DEPENDENCY GRAPH
   Draw a text-based dependency diagram showing every module and their import relationships.
   No circular dependencies allowed.

2. ALL PROTOCOL DEFINITIONS (write as actual Python code)
   Define these Python Protocol classes with full type signatures:

   - MarketDataProvider (in backend/data_ingestion/protocols.py)
     Methods: fetch_daily_bars, fetch_latest_price, get_available_symbols
     Must support batch operations for efficiency on Pi hardware

   - BrokerAdapter (in backend/trading/broker_adapter.py)
     Exactly as defined in CLAUDE.md — this is sacred, do not modify the interface

   - AnalysisEngine (in backend/analysis/engine.py)
     Methods: compute_indicators, score_symbol, rank_symbols
     Must accept a DataFrame of OHLCV bars, return typed results

   - Indicator (in backend/analysis/indicators/base.py)
     Base class/protocol for individual indicator implementations
     compute(df: DataFrame) -> Series interface

3. DATA CONTRACTS
   Define Python dataclasses or Pydantic models for all data passed between modules:
   - OHLCVBar, IndicatorResult, SymbolScore, RankedSymbol
   - Order, Position, AccountBalance, OrderStatus
   - PortfolioSnapshot, TradeRecord, PerformanceMetrics

4. API CONTRACT
   List every API endpoint the frontend will need. For each:
   - Method + path
   - Request params
   - Response schema (Pydantic model)
   - Which database query it maps to

5. CONFIGURATION SCHEMA
   All environment variables the system needs. For each: name, type, default, description.

Write all Protocol and dataclass definitions as actual working Python files,
not pseudocode. Save them to their respective paths under backend/.

End with ## Handoff notes for the Backend Architect and Data Engineer.
```

### ⚡ Database Optimizer

```
Activate Database Optimizer.

Read CLAUDE.md first. Follow all directives.

Context: read docs/research/sector-study.md to understand the data volume
(~30-50 symbols, daily bars, long history for backtesting).

Your mission: design and implement the complete database layer.

Deliver:

1. TIMESCALEDB SCHEMA (as actual Alembic migration files)

   Hypertables (time-series):
   - market_bars: symbol, ts, open, high, low, close, volume, adj_close
     Chunk interval: 1 month. Compression after 6 months.
   - indicator_values: symbol, ts, indicator_name, value
     Flexible — allows adding new indicators without schema changes
   - portfolio_nav: ts, cash, equity, total, benchmark_value
     Continuous aggregate: daily_nav_summary (weekly rollup)

   Regular tables:
   - portfolio_positions: symbol, qty, avg_cost, current_price, unrealized_pnl, updated_at
   - trade_orders: id, symbol, side, qty, price, status, reason, strategy_version, ts
   - algorithm_signals: symbol, ts, score, action, reason, indicator_snapshot (jsonb)
   - watchlist: symbol, sector, asset_class, notes, active, added_at
   - experiment_runs: id, strategy_version, started_at, ended_at, config (jsonb), notes

2. INDEXES
   Define exactly which indexes to create and explain why each one is necessary
   (query pattern it serves). Do not create indexes "just in case".

3. CONTINUOUS AGGREGATES
   - weekly_performance: pre-computed weekly P&L rollup
   - monthly_signal_accuracy: pre-computed monthly signal hit rate

4. SQLALCHEMY MODELS
   Write all models in backend/db/models.py using SQLAlchemy 2.x declarative style
   with async support.

5. QUERY MODULES
   Write backend/db/queries/market_queries.py and portfolio_queries.py with
   the 10 most important queries the API will need. Use parameterized queries only.

6. docs/architecture/schema.md
   Entity-relationship diagram in text form + explanation of each table's role.

End with ## Handoff notes for Data Engineer and Backend Architect.
```

### ⚡ Workflow Architect

```
Activate Workflow Architect.

Read CLAUDE.md first. Follow all directives.

Your mission: map the complete workflow tree for the autonomous trading system.

Produce docs/architecture/workflow-tree.md covering every path the system can take:

1. DAILY JOB SEQUENCE (happy path)
   Map the exact sequence:
   07:00 fetch_market_data → 07:30 run_analysis → 08:00 execute_paper_trades → 08:15 update_portfolio_nav
   For each job: inputs, outputs, DB operations, success criteria.

2. FAILURE MODES AND RECOVERY
   For each job, map every failure scenario:
   - yfinance API unavailable → fallback to Twelve Data → if both fail, skip day and log
   - Scheduler crashed mid-job → idempotency check on restart, resume or skip?
   - DB write fails during trade execution → rollback strategy
   - Analysis produces no signals → portfolio holds, log reason
   - Market closed (weekends, holidays) → how does the system detect and skip?

3. DATA FLOW DIAGRAM
   Trace the path of a single stock symbol through the entire system:
   raw API response → normalized OHLCV → indicator computation → scoring →
   signal generation → order decision → paper execution → portfolio update → dashboard

4. STATE MACHINE FOR TRADE ORDERS
   Define all states an order can be in and valid transitions:
   PENDING → FILLED, PENDING → REJECTED, FILLED → (terminal), etc.

5. SCHEDULER RECOVERY BEHAVIOR
   What happens when the Pi reboots at various points in the day?
   Define behavior for: before 07:00, between jobs, after all jobs complete.

6. MONITORING HOOKS
   What should be logged at each step so the dashboard can show system health?
   Define log structure (structured JSON logs recommended).

End with ## Handoff notes for Backend Architect and DevOps Automator.
```

---

## PHASE 2 — Financial Domain
*Run all three in parallel ⚡ after Phase 0 is complete. Can overlap with Phase 1.*

### ⚡ Financial Analyst

```
Activate Financial Analyst.

Read CLAUDE.md first. Follow all directives.
Read docs/research/sector-study.md for context on the asset universe and strategy approach.

Your mission: define the complete performance measurement layer for the simulation.

Produce docs/finance/performance-metrics.md and implement the metric computation functions.

1. PORTFOLIO PERFORMANCE METRICS
   Define and implement computation for:
   - Total Return (absolute and %)
   - CAGR (Compound Annual Growth Rate)
   - Sharpe Ratio (use risk-free rate as env var, default 4.5%)
   - Sortino Ratio (downside deviation only)
   - Maximum Drawdown (with recovery period)
   - Calmar Ratio (CAGR / Max Drawdown)
   - Win Rate (% of profitable trades)
   - Profit Factor (gross profit / gross loss)
   - Average Win vs Average Loss
   - Alpha and Beta vs benchmark (benchmark defined in sector study)

2. SIGNAL QUALITY METRICS
   How do we measure if the algorithm's signals are actually predictive?
   - Signal accuracy (did buy signals lead to gains within N days?)
   - Signal hit rate by sector
   - Average holding period profitability

3. IMPLEMENTATION
   Write backend/analysis/performance/metrics.py with all computation functions.
   All functions must accept a DataFrame as input, return typed numeric results.
   No side effects, pure functions only.

4. PERFORMANCE THRESHOLDS
   Define what "good" looks like for this simulation:
   - What Sharpe ratio indicates the algorithm is working?
   - What drawdown is acceptable?
   - What win rate is the minimum acceptable?
   These become the alert thresholds in the dashboard.

End with ## Handoff notes for AI Engineer and Frontend Developer (what to display).
```

### ⚡ FP&A Analyst

```
Activate FP&A Analyst.

Read CLAUDE.md first. Follow all directives.
Read docs/research/sector-study.md and wait for Financial Analyst output if available.

Your mission: define the reporting and P&L structure for the simulation.

Produce docs/finance/reporting-structure.md covering:

1. SIMULATION P&L STRUCTURE
   How is virtual P&L calculated and reported?
   - Realized vs unrealized gains
   - Daily, weekly, monthly, YTD breakdowns
   - Per-symbol P&L attribution
   - Per-sector P&L attribution

2. PERIOD-OVER-PERIOD REPORTING
   Define how to compare performance across time periods:
   - This week vs last week
   - This month vs benchmark
   - Rolling 30/60/90 day windows
   What queries pre-compute these efficiently in TimescaleDB?

3. SIMULATION HEALTH INDICATORS
   What KPIs tell us if the simulation is running correctly vs if the algorithm is good?
   (These are different: a broken scheduler vs a bad strategy look different in the data)

4. DASHBOARD SUMMARY CARDS
   Define exactly what appears on the main dashboard as summary cards:
   - Card name, metric, calculation, good/bad threshold, update frequency

5. EXPORT FORMAT
   Define a CSV/JSON export format for simulation results
   (for future backtesting comparison).

End with ## Handoff notes for Frontend Developer (what cards and tables to build).
```

### ⚡ Experiment Tracker

```
Activate Experiment Tracker.

Read CLAUDE.md first. Follow all directives.

Your mission: design the framework that allows comparing different algorithm versions.

The core problem: the scoring algorithm will be iterated on over time. We need to know
which version of the algorithm was active during which simulation period, and compare
their performance objectively.

Produce docs/finance/experiment-framework.md and backend/experiments/ skeleton.

1. EXPERIMENT MODEL
   Define what constitutes an "experiment" in this system:
   - Strategy version identifier
   - Configuration snapshot (all weights, thresholds, parameters active at that time)
   - Start and end date
   - Performance results for that period
   - How to isolate experiment results from others

2. VERSION TRACKING
   How does the system record which strategy version generated each signal and trade?
   All trade_orders and algorithm_signals must reference a strategy_version.
   How is strategy_version assigned at startup?

3. COMPARISON FRAMEWORK
   How do we compare experiment A vs experiment B?
   - Standardized metrics (from Financial Analyst output)
   - Statistical significance considerations (is the difference real or noise?)
   - Visualization data format for comparison charts

4. IMPLEMENTATION
   Write backend/experiments/ module skeleton:
   - experiments/tracker.py: records experiment runs to DB
   - experiments/comparator.py: queries and compares experiment results
   These are stubs with full interfaces, minimal implementation.

End with ## Handoff notes for AI Engineer and Analytics Reporter.
```

---

## PHASE 3 — Design
*Run both in parallel ⚡. Requires Phase 0 and Phase 2 output.*

### ⚡ UI Designer

```
Activate UI Designer.

Read CLAUDE.md first. Follow all directives.
Read: docs/research/sector-study.md, docs/finance/performance-metrics.md,
docs/finance/reporting-structure.md

Your mission: design the visual system for the trading dashboard.

Financial dashboards have specific conventions. This must look professional,
not like a generic SaaS template.

Produce docs/design/ui-system.md and CSS custom property files.

1. COLOR SYSTEM
   Financial-specific color tokens:
   - Gain color (standard market green, not generic success green)
   - Loss color (standard market red)
   - Neutral/flat color
   - Chart line colors for multi-series (portfolio, benchmark, individual positions)
   - Background system (dark theme primary — financial dashboards are dark)
   - Surface hierarchy (background, card, elevated card, overlay)

2. TYPOGRAPHY
   - Font stack (system fonts preferred for performance on Pi)
   - Size scale for: large numbers (portfolio value), labels, body text, captions
   - Monospace for prices and numeric data (tabular figures)

3. COMPONENT SPECIFICATIONS
   Define visual specs (not code) for:
   - Price change badge (±% with color)
   - Portfolio value card (large number + sparkline)
   - Trade status chip (FILLED, PENDING, REJECTED)
   - Signal strength indicator (score 0-100 with visual encoding)
   - Market status indicator (open/closed/pre-market)
   - Chart color palette for candlesticks (wick, body up, body down)

4. LAYOUT GRID
   Define the dashboard layout grid system — how cards arrange at different viewport sizes.
   The Pi will likely be accessed from desktop browsers, but mobile should work.

5. IMPLEMENTATION
   Write frontend/src/lib/styles/tokens.css with all CSS custom properties.
   Write frontend/src/lib/styles/base.css with reset and base styles.

End with ## Handoff notes for Frontend Developer.
```

### ⚡ UX Architect

```
Activate UX Architect.

Read CLAUDE.md first. Follow all directives.
Read: docs/research/sector-study.md, docs/finance/reporting-structure.md,
docs/architecture/module-contracts.md (API endpoints section)

Your mission: define the information architecture and interaction design for the dashboard.

This is a single-user monitoring tool. The user needs to quickly understand:
1. Is the algorithm running correctly?
2. Is the portfolio performing well?
3. What did it do today?
4. What does the market look like right now?

Produce docs/design/ux-architecture.md and the SvelteKit route skeleton.

1. INFORMATION HIERARCHY
   What is the most important information? Map it to screen real estate.
   Above the fold on main dashboard: what are the top 3-5 things the user sees first?

2. NAVIGATION STRUCTURE
   Define all routes and what each page shows:
   - / (main dashboard)
   - /portfolio (detailed positions and history)
   - /market (watchlist with prices, scores, charts)
   - /trades (trade history, filters, detail view)
   - /experiments (algorithm comparison, version history)
   - /system (scheduler status, last job times, error log)

3. PAGE LAYOUTS (text wireframes)
   For each route, produce a text wireframe showing component placement.
   Use ASCII art or structured text. Example:
   ```
   [HEADER: Portfolio Value $X | Daily P&L +$Y (+Z%)]
   [NAV: Dashboard | Portfolio | Market | Trades | System]
   [CARD: Balance] [CARD: Today's Trades] [CARD: Algorithm Status]
   [CHART: NAV over time — full width]
   [TABLE: Top signals today] [TABLE: Open positions]
   ```

4. DATA REFRESH STRATEGY
   The dashboard shows data from a system that updates once per day.
   Define: which elements poll the API and how often? (portfolio: every 5min?
   market prices: every 1min during market hours? system status: every 30s?)

5. IMPLEMENTATION
   Create the SvelteKit route skeleton:
   - frontend/src/routes/+page.svelte (empty with layout comment)
   - frontend/src/routes/portfolio/+page.svelte
   - frontend/src/routes/market/+page.svelte
   - frontend/src/routes/trades/+page.svelte
   - frontend/src/routes/experiments/+page.svelte
   - frontend/src/routes/system/+page.svelte
   Each file should have a comment block describing what it will contain.

End with ## Handoff notes for Frontend Developer.
```

---

## PHASE 4 — Backend Implementation
*Run sequentially →. Each depends on the previous.*

### → Data Engineer

```
Activate Data Engineer.

Read CLAUDE.md first. Follow all directives.

Depends on (read these before starting):
- docs/architecture/module-contracts.md (MarketDataProvider Protocol)
- docs/architecture/schema.md (market_bars table structure)
- backend/data_ingestion/protocols.py (already written by Software Architect)
- backend/db/models.py (already written by Database Optimizer)
- docs/research/sector-study.md (understand the asset universe)

Your mission: implement the complete data ingestion pipeline.

1. YFINANCE PROVIDER (backend/data_ingestion/providers/yfinance_provider.py)
   Implement MarketDataProvider protocol using yfinance:
   - fetch_daily_bars(symbols: list[str], start: date, end: date) -> dict[str, DataFrame]
   - Use yf.download() with list of tickers in one call (most efficient)
   - Validate: check for missing data, zero volume, suspiciously large gaps
   - Normalize: ensure consistent column names, UTC timestamps, no timezone ambiguity
   - Idempotent upsert into market_bars (ON CONFLICT DO UPDATE)

2. TWELVE DATA PROVIDER (backend/data_ingestion/providers/twelve_data_provider.py)
   Implement same MarketDataProvider protocol as fallback:
   - Same interface as yfinance provider
   - Respect free tier: 800 req/day, batch where possible
   - Graceful handling of rate limit errors (retry with backoff)

3. PROVIDER SELECTION
   Implement provider selection via MARKET_DATA_PROVIDER env var.
   Auto-fallback: if primary raises ProviderError, try secondary once, then give up and log.

4. DATA VALIDATION LAYER (backend/data_ingestion/validation.py)
   Functions to detect:
   - Missing trading days (compare against market calendar)
   - Stale data (last bar timestamp too old)
   - Price anomalies (single-day moves > 50% flagged as suspicious)

5. MARKET CALENDAR
   Use pandas_market_calendars to know which days are trading days.
   The scheduler must check this before attempting to fetch data.

All writes to DB must be idempotent — running the job twice on the same day must
produce the same result, not duplicate rows.

End with ## Handoff notes for Backend Architect.
```

### → Backend Architect

```
Activate Backend Architect.

Read CLAUDE.md first. Follow all directives.

Depends on (read these before starting):
- docs/architecture/module-contracts.md (all protocols and API contracts)
- docs/architecture/workflow-tree.md (job sequence and failure modes)
- docs/finance/performance-metrics.md (what the portfolio needs to compute)
- backend/data_ingestion/ (Data Engineer output — already implemented)
- backend/db/ (Database Optimizer output — models and queries ready)

Your mission: implement the core backend services.

1. PAPER BROKER (backend/trading/paper_broker.py)
   Implement BrokerAdapter Protocol for simulation:
   - place_order: validates order, writes to trade_orders with status FILLED (instant fill)
     Apply a configurable slippage model: price = market_price * (1 + SLIPPAGE_PCT)
     SLIPPAGE_PCT env var, default 0.001 (0.1%)
   - get_positions: reads from portfolio_positions
   - get_account_balance: reads from portfolio_positions + cash in DB
   - get_order_status: reads from trade_orders

2. PORTFOLIO MANAGER (backend/trading/portfolio_manager.py)
   - Calls BrokerAdapter (never paper_broker directly)
   - execute_signals(signals: list[RankedSymbol]): for top-N signals, compute position size
     via RiskManager, call broker.place_order
   - update_positions(): recalculate unrealized P&L at current prices
   - snapshot_nav(): write current portfolio value to portfolio_nav

3. RISK MANAGER (backend/trading/risk_manager.py)
   - Fixed fractional position sizing: invest MAX_POSITION_PCT of portfolio per symbol
     MAX_POSITION_PCT env var, default 0.05 (5%)
   - MAX_OPEN_POSITIONS env var, default 10
   - Cash reserve: always keep MIN_CASH_PCT (default 20%) as dry powder
   - compute_position_size(symbol, score, portfolio_value) -> qty

4. FASTAPI APPLICATION (backend/api/main.py + routers/)
   Implement all endpoints defined in docs/architecture/module-contracts.md:

   GET /api/portfolio/summary      → balance, equity, P&L, positions count
   GET /api/portfolio/positions     → all open positions with unrealized P&L
   GET /api/portfolio/nav           → historical NAV time series
   GET /api/portfolio/performance   → Sharpe, drawdown, CAGR, win rate
   GET /api/trades                  → trade history with filters (symbol, date range)
   GET /api/market/bars/{symbol}    → OHLCV bars for a symbol
   GET /api/market/watchlist        → watchlist with latest prices and scores
   GET /api/algorithms/signals      → latest signals with scores and reasons
   GET /api/algorithms/experiments  → experiment runs comparison
   GET /api/system/status           → scheduler last run times, next run times, errors

5. SCHEDULER JOBS (backend/scheduler/jobs.py)
   Implement the 4 daily jobs following the workflow tree:
   - fetch_market_data(): checks market calendar, calls data provider
   - run_analysis(): calls analysis engine on all watchlist symbols
   - execute_paper_trades(): calls portfolio_manager.execute_signals()
   - update_portfolio_nav(): calls portfolio_manager.snapshot_nav()
   Each job logs structured JSON to stdout (picked up by Docker logs).

End with ## Handoff notes for AI Engineer and Frontend Developer.
```

### → AI Engineer

```
Activate AI Engineer.

Read CLAUDE.md first. Follow all directives.

Depends on (read these before starting):
- docs/research/sector-study.md (what signals matter, signal taxonomy)
- docs/finance/performance-metrics.md (what metrics to compute)
- docs/finance/experiment-framework.md (how to version strategies)
- docs/architecture/module-contracts.md (AnalysisEngine and Indicator protocols)
- backend/analysis/engine.py (Protocol already written by Software Architect)

IMPORTANT: The specific algorithm weights and thresholds are NOT defined yet.
Your job is to build the ENGINE and INFRASTRUCTURE, not hardcode a strategy.
Everything configurable must be an env var or loaded from a config file.

Your mission: implement the analysis engine with extensible, configurable structure.

1. BASE INDICATOR (backend/analysis/indicators/base.py)
   Abstract base class:
   - compute(df: DataFrame) -> Series
   - name: str property
   - required_periods: int (minimum bars needed)
   All indicators must fail gracefully if not enough data (return NaN series).

2. PLACEHOLDER INDICATORS (3 implementations — real math, configurable params)
   - backend/analysis/indicators/moving_average.py
     SimpleMovingAverage and ExponentialMovingAverage
     Params: period (env var or config)
   - backend/analysis/indicators/momentum.py
     RSI implementation (use ta library, not manual)
     Params: period, overbought threshold, oversold threshold
   - backend/analysis/indicators/volatility.py
     ATR (Average True Range)
     Params: period

3. COMPOSITE SCORER (backend/analysis/scoring/composite_scorer.py)
   - Loads indicator weights from config (YAML file or env vars)
   - compute_score(symbol: str, bars: DataFrame) -> SymbolScore
   - score is 0-100 normalized
   - Stores intermediate indicator values to indicator_values table
   - Records final score to algorithm_signals with full indicator_snapshot in jsonb
   - Tags result with current STRATEGY_VERSION env var

4. SYMBOL RANKER (backend/analysis/scoring/ranker.py)
   - rank_symbols(watchlist: list[str]) -> list[RankedSymbol]
   - Returns symbols sorted by score, descending
   - Filters out symbols with insufficient data (< required_periods bars)
   - Filters out symbols flagged as suspicious by data validation

5. STRATEGY CONFIG (backend/analysis/config.py)
   Load strategy configuration from:
   - Environment variables (highest priority)
   - config/strategy.yaml (version-controlled defaults)
   Config includes: indicator weights, score thresholds, min score to act on,
   strategy version string.

End with ## Handoff notes for Frontend Developer and Analytics Reporter.
```

---

## PHASE 5 — Frontend + Infrastructure
*Run both in parallel ⚡. Requires Phases 3 and 4.*

### ⚡ Frontend Developer

```
Activate Frontend Developer.

Read CLAUDE.md first. Follow all directives.

Depends on (read these before starting):
- docs/design/ui-system.md (visual system from UI Designer)
- docs/design/ux-architecture.md (layouts, routes, wireframes from UX Architect)
- docs/architecture/module-contracts.md (API endpoints and response schemas)
- docs/finance/reporting-structure.md (what cards and metrics to display)
- docs/finance/performance-metrics.md (what performance numbers to show)
- frontend/src/lib/styles/ (tokens.css and base.css from UI Designer)
- frontend/src/routes/ (route skeletons from UX Architect)

Your mission: implement the complete SvelteKit dashboard.

Use SvelteKit with static adapter. All API calls to FastAPI backend at /api/.
Use Chart.js + chartjs-chart-financial for all charts.

1. SHARED COMPONENTS (frontend/src/lib/components/)
   - PriceChange.svelte: displays ±% with financial color coding
   - MetricCard.svelte: summary card with value, label, threshold indicator
   - LoadingSpinner.svelte and ErrorBoundary.svelte
   - StatusBadge.svelte: FILLED/PENDING/REJECTED/OPEN/CLOSED chips
   - SignalScore.svelte: 0-100 score with visual bar

2. MAIN DASHBOARD (/)
   Following UX Architect wireframe:
   - Header: portfolio total value, daily P&L, daily % change
   - Summary cards: Sharpe ratio, max drawdown, win rate, open positions
   - NAV performance chart: line chart, portfolio value vs benchmark over time
   - Today's signals: top 5 buy signals with scores
   - Recent trades: last 10 executions

3. PORTFOLIO PAGE (/portfolio)
   - Open positions table: symbol, qty, avg cost, current price, unrealized P&L, % change
   - Performance metrics panel: all metrics from Financial Analyst
   - NAV chart with date range selector (7d, 30d, 90d, 1y, all)

4. MARKET PAGE (/market)
   - Watchlist table: symbol, sector, current price, daily change, score
   - Per-symbol detail: click symbol → candlestick chart (last 90 days) + indicators overlay
   - Candlestick chart must show: OHLC candles + volume bars + optional MA overlay

5. TRADES PAGE (/trades)
   - Filterable table: date range, symbol, side (buy/sell), status
   - Trade detail: show the reason/signal that triggered the trade

6. EXPERIMENTS PAGE (/experiments)
   - Table of experiment runs with performance comparison
   - Simple comparison: side-by-side metrics for two selected experiments

7. SYSTEM PAGE (/system)
   - Scheduler status: last run time and status for each of the 4 jobs
   - Next scheduled run times
   - Recent error log
   - Data freshness indicator: last bar timestamp for each symbol

All pages must handle: loading state, empty state, error state.
Data refresh: poll /api/system/status every 30s; market prices every 60s during market hours.

End with ## Handoff notes for Analytics Reporter.
```

### ⚡ DevOps Automator

```
Activate DevOps Automator.

Read CLAUDE.md first. Follow all directives. ARM64 compatibility is mandatory.

Depends on (read these before starting):
- docs/architecture/workflow-tree.md (service startup and recovery behavior)
- backend/ structure (all services to containerize)
- frontend/ structure (SvelteKit static build process)

Your mission: create the complete Docker infrastructure.

1. DOCKERFILE (docker/Dockerfile) — multi-stage
   Stage 1 — Frontend build (node:20-alpine, ARM64):
   - Copy frontend/
   - npm ci && npm run build
   - Output: /app/frontend/build/

   Stage 2 — Python base (python:3.12-slim, ARM64):
   - Install system deps: build-essential, libpq-dev
   - pip install all Python requirements
   - Copy backend/
   - Copy frontend build from Stage 1 into backend/static/

   Two entrypoints:
   - CMD ["uvicorn", "api.main:app", ...] for api service
   - CMD ["python", "-m", "scheduler.main"] for scheduler service

2. DOCKER-COMPOSE (docker/docker-compose.yml)
   Services:
   - db: timescale/timescaledb:latest-pg16
     Volume: postgres_data
     Healthcheck: pg_isready
     Env: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD from .env

   - api: builds from Dockerfile with API entrypoint
     Port: 8000:8000
     Depends on: db (condition: service_healthy)
     Env: all from .env
     Restart: unless-stopped

   - scheduler: same image as api, different entrypoint
     Depends on: db (condition: service_healthy)
     Env: all from .env
     Restart: unless-stopped

3. ENV FILE (.env.example)
   Document every variable. Group by concern:
   # Database
   POSTGRES_DB=trader
   POSTGRES_USER=trader
   POSTGRES_PASSWORD=changeme

   # Application
   BROKER_ADAPTER=paper
   MARKET_DATA_PROVIDER=yfinance
   TWELVE_DATA_API_KEY=your_key_here
   INITIAL_VIRTUAL_CAPITAL=10000
   STRATEGY_VERSION=v0.1.0

   # Risk parameters
   MAX_POSITION_PCT=0.05
   MAX_OPEN_POSITIONS=10
   MIN_CASH_PCT=0.20
   SLIPPAGE_PCT=0.001

   # Analysis
   RISK_FREE_RATE=0.045

4. REQUIREMENTS FILES
   - backend/requirements.txt: pin all versions
     fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic,
     apscheduler, yfinance, pandas, numpy, ta, pandas_market_calendars,
     requests, pydantic, pydantic-settings, python-dotenv

5. STARTUP SCRIPT (docker/init-db.sh)
   - Wait for TimescaleDB to be ready
   - Run alembic upgrade head
   - Insert default watchlist from a seed file if watchlist table is empty

6. README (docker/README.md)
   How to start the system on a fresh Raspberry Pi:
   - Install Docker + Docker Compose on Raspberry Pi OS
   - Clone repo, copy .env.example to .env, fill in values
   - docker compose up -d
   - How to view logs, how to access the dashboard

End with ## Handoff notes for Reality Checker.
```

---

## PHASE 6 — Quality Gates
*Run sequentially →.*

### → Analytics Reporter

```
Activate Analytics Reporter.

Read CLAUDE.md first. Follow all directives.

Depends on (read all of these):
- docs/finance/performance-metrics.md
- docs/finance/reporting-structure.md
- docs/design/ux-architecture.md
- backend/api/routers/ (what endpoints exist)
- frontend/src/routes/ (what the dashboard shows)

Your mission: validate the analytics layer is complete and correct.

Produce docs/qa/analytics-checklist.md:

1. KPI COMPLETENESS AUDIT
   For every metric defined by Financial Analyst and FP&A Analyst:
   - Is it computed in backend/analysis/performance/metrics.py? ✓/✗
   - Is it exposed by a FastAPI endpoint? ✓/✗
   - Is it displayed in the frontend? ✓/✗
   - Is the formula correct? ✓/✗ (verify the math)

2. DATA FLOW VERIFICATION
   Trace each data type from source to display:
   - Market bar: yfinance → market_bars → /api/market/bars → candlestick chart
   - NAV: update_portfolio_nav job → portfolio_nav → /api/portfolio/nav → NAV chart
   - Signal: run_analysis job → algorithm_signals → /api/algorithms/signals → signals panel
   For each trace: is every step implemented? Are there gaps?

3. MISSING METRICS
   Identify any metrics that were defined in docs/finance/ but not implemented.
   Flag these as blockers or nice-to-haves.

4. EDGE CASES IN REPORTING
   What happens in these cases?
   - Portfolio has never made a trade yet (day 1)
   - All positions are at a loss
   - The benchmark API is unavailable (Sharpe ratio needs benchmark)
   - Experiment has less than 30 days of data (statistical significance issue)

End with ## Handoff notes for Security Engineer listing any gaps found.
```

### → Security Engineer

```
Activate Security Engineer.

Read CLAUDE.md first. Follow all directives.

Audit the entire codebase for security issues. Produce docs/qa/security-audit.md
and apply fixes directly to the code.

AUDIT CHECKLIST:

1. SECRETS MANAGEMENT
   - Scan all files for hardcoded credentials, API keys, passwords
   - Verify .env.example contains only placeholder values (no real keys)
   - Verify .gitignore includes .env
   - Verify Docker Compose passes secrets via env vars, not build args

2. API SECURITY
   - CORS configuration: should only allow the local network origin
   - Input validation on all FastAPI endpoints (Pydantic models in use?)
   - SQL injection: verify all queries use SQLAlchemy parameterized statements
   - Rate limiting: is the API exposed to the internet or only local network?
   - No authentication is acceptable (single-user, local-only tool)

3. DOCKER SECURITY
   - Containers not running as root?
   - No privileged containers
   - No unnecessary port exposure (only 8000 should be exposed)
   - DB port (5432) NOT exposed to host

4. DEPENDENCY AUDIT
   - Check requirements.txt for any packages with known CVEs
   - Flag any packages that are not actively maintained

5. DATA HANDLING
   - No real financial credentials stored anywhere (this is paper trading only)
   - API keys (Twelve Data) stored securely, not logged

Apply fixes directly. For issues that cannot be fixed automatically, document them
as MUST FIX or ADVISORY in the audit report.

End with ## Handoff notes for Reality Checker listing any remaining blockers.
```

### → Reality Checker

```
Activate Reality Checker.

Read CLAUDE.md first. The Reality Checker checklist at the bottom of CLAUDE.md
is your acceptance criteria. Default to NEEDS WORK unless you have overwhelming evidence.

Read ALL previous phase outputs before making any judgment.

Your mission: verify the system is actually complete and functional.

Go through the CLAUDE.md Reality Checker checklist item by item.
For each item: PASS, FAIL, or CANNOT VERIFY (explain why).

Beyond the checklist, verify:

1. DEPENDENCY COMPLETENESS
   Is every dependency listed in requirements.txt? Are versions pinned?
   Are there any imports in the code that are not in requirements.txt?

2. PROTOCOL COMPLIANCE
   Is BrokerAdapter implemented correctly everywhere?
   Does PortfolioManager ever call paper_broker directly (violation)?
   Does MarketDataProvider protocol match the implementations?

3. CONFIGURATION COMPLETENESS
   Is every env var used in code also documented in .env.example?
   Are there any hardcoded values that should be env vars?

4. DATABASE CONSISTENCY
   Do the SQLAlchemy models match the Alembic migrations?
   Are all columns referenced in queries actually defined in models?

5. API ↔ FRONTEND CONSISTENCY
   Does the frontend call endpoints that actually exist in FastAPI?
   Do the response schemas match what the frontend expects?

6. STUB COMPLETENESS
   Are the analysis/indicators/ and analysis/scoring/ modules properly stubbed?
   Do they have clean interfaces that allow future implementation without breaking changes?

Output: a PASS/FAIL report with specific file:line references for every FAIL.
If more than 3 blockers exist, the system is NOT ready. List what needs to be fixed
and which agent should fix it.
```

---

## Notes on running this

- **Context passing**: Each agent's output documents are the context for the next agent.
  Always point the next agent to the relevant docs explicitly in the prompt.

- **Parallel agents**: When running agents in parallel, start them in separate Claude Code
  conversations. Each reads CLAUDE.md independently.

- **Blocked agents**: If an agent reports it cannot proceed (missing input from a prior phase),
  complete the blocking phase first. Do not skip phases.

- **Iteration**: After Reality Checker flags issues, re-activate the responsible agent
  with the specific failure description. They have all the context in docs/.

- **The algorithm comes later**: When the sector study is done and you are ready to define
  the actual scoring algorithm, re-activate AI Engineer with the completed sector study
  and a new scoring config. The infrastructure accepts it without changes.
