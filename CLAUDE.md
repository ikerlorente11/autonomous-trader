# Autonomous Trader — Project Directives

This file is the **constitution of the project**. Every agent working on this codebase must read it before doing anything. Rules here override individual agent defaults.

---

## What this project is

An autonomous paper-trading system that:
- Fetches daily market data (stocks, ETFs, indexes)
- Scores and ranks assets using technical analysis
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
    def place_order(self, symbol: str, side: str, qty: int, order_type: str) -> Order: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_balance(self) -> Decimal: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
```

- `PortfolioManager` calls `BrokerAdapter` — never a concrete broker directly
- `PaperBroker` is the only implementation in Phase 1
- Switching to real trading = changing `BROKER_ADAPTER=paper` to `BROKER_ADAPTER=alpaca` in `.env`
- No other code changes allowed for the swap

**Any agent that bypasses this protocol will have their work rejected by the Reality Checker.**

---

## What is intentionally undefined

These modules have their **interfaces defined** but no business logic yet. They will be filled after the sector study is complete. Every agent must leave them as clean stubs:

- `analysis/indicators/` — which indicators to use (leave placeholder: MovingAverage, RSI, ATR stubs)
- `analysis/scoring/` — how to weight and rank signals (leave configurable via env/config, no hardcoded weights)
- `trading/risk_manager.py` — position sizing rules (leave configurable %, no hardcoded values)
- `watchlist` table — which symbols/sectors to track (leave empty, populated at runtime)

---

## Agent roster and responsibilities

### Phase 0 — Research (before any code)

| Agent | Responsibility | Output |
|---|---|---|
| **Investment Researcher** | Study market sectors, asset classes, financial metrics that matter for scoring. Define what a "good" investment signal looks like. | `docs/research/sector-study.md` — universe of assets, metrics, signal taxonomy |

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
Investment Researcher
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
│   │   └── sector-study.md            ← Investment Researcher
│   ├── architecture/
│   │   ├── module-contracts.md        ← Software Architect
│   │   ├── schema.md                  ← Database Optimizer
│   │   └── workflow-tree.md           ← Workflow Architect
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
│   │   ├── protocols.py               ← MarketDataProvider Protocol
│   │   └── providers/
│   │       ├── yfinance_provider.py
│   │       └── twelve_data_provider.py
│   ├── analysis/
│   │   ├── indicators/                ← stubs only (filled later)
│   │   ├── scoring/                   ← stubs only (filled later)
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

## Market data sources

| Source | Role | API Key required |
|---|---|---|
| `yfinance` | Primary — daily OHLCV batch | No |
| Twelve Data (free tier) | Fallback when yfinance is unavailable | Yes (`TWELVE_DATA_API_KEY`) |

Both implement `MarketDataProvider`. Selection via `MARKET_DATA_PROVIDER=yfinance` env var.

---

## Daily job sequence (scheduler)

```
07:00 UTC  →  fetch_market_data()       ← Data Engineer
07:30 UTC  →  run_analysis()            ← AI Engineer
08:00 UTC  →  execute_paper_trades()    ← Backend Architect
08:15 UTC  →  update_portfolio_nav()    ← Backend Architect
```

All jobs are idempotent. If a job runs twice on the same day, it must not create duplicate data.
All jobs write `misfire_grace_time=3600` — if missed, run within 1 hour or skip.

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
