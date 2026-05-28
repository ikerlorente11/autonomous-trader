<!-- Agent: UX Architect | Phase: 3 | Depends on: docs/research/00-signal-synthesis.md, docs/finance/reporting-structure.md, docs/architecture/module-contracts.md, docs/design/ui-system.md -->

# Phase 3 — UX Architecture & Information Design

Information architecture and interaction design for the single-user monitoring
dashboard. This document tells the Frontend Developer *what goes where, why, and
how often it refreshes*. The visual language (colors, type, component specs) is
owned by the UI Designer (`ui-system.md`); the P&L/health semantics are owned by
FP&A (`reporting-structure.md`); the API surface is owned by the Software Architect
(`module-contracts.md` §4). This document binds those three into screens.

> **The four questions the user actually asks** (from the brief) drive every
> layout decision below:
> 1. *Is the algorithm running correctly?* → **Health** (status palette)
> 2. *Is the portfolio performing well?* → **Performance** (P&L palette)
> 3. *What did it do today?* → **Activity** (today's trades, ranked signals)
> 4. *What does the market look like right now?* → **Context** (regime, watchlist)
>
> **Load-bearing UX rule inherited from FP&A §3/§4 and UI Designer A.1/A.2:**
> *money and health never share a color language.* Performance uses `--pnl-*`
> (green/red); health and regime use `--status-*` (ok/warn/critical). A green
> "system OK" chip must never read as "made money." Every screen below honors this.

---

## SECTION 1 — INFORMATION HIERARCHY

This is a **glance-first** tool. The system updates once per day (08:15 UTC NAV
snapshot); the user opens the dashboard to confirm health and check results, not to
trade live. So the hierarchy optimizes for *time-to-confidence*, not interactivity.

### 1.1 Priority tiers (most → least important)

| Tier | Question answered | Screen real estate | Palette |
|---|---|---|---|
| **T0 — Trust** | Is the machine running? Is the data fresh? | Persistent header chip + banner when broken | status |
| **T1 — Outcome** | What is it worth and how is it doing? | Above-the-fold card row | P&L |
| **T2 — Context** | What posture is the algo in and why? | Regime/exposure chips adjacent to cards | status |
| **T3 — Activity** | What did it do today? | NAV chart + today's trades + ranked signals | mixed |
| **T4 — Detail** | Drill into any of the above | Dedicated routes (`/portfolio`, `/market`, …) | mixed |

**T0 ranks above T1 deliberately** (FP&A §3.1): a red P&L during RISK_OFF can be
*correct behavior*, but a broken pipeline makes every number a lie. The user must
be able to trust the numbers before reading them — so health is always visible and
a broken state pre-empts the performance story with a banner.

### 1.2 Above-the-fold on the main dashboard — top 5 things seen first

In reading order (top-left → right), what a user sees in the first second:

1. **Simulation Health chip** (header, always visible) — one of OK / DEGRADED /
   BROKEN. When not OK, a non-dismissible banner appears below the header.
   *(FP&A Card 9; status palette.)*
2. **Portfolio Value (NAV)** + daily Δ% — the hero number. *(FP&A Card 1; P&L.)*
3. **Today's P&L** ($ and %) — what happened today. *(FP&A Card 2; P&L.)*
4. **Market Regime chip** (RISK_ON / CAUTION / RISK_OFF) — the posture lens through
   which today's P&L should be read. *(FP&A Card 8; status palette.)*
5. **NAV-over-time chart** with SPY benchmark overlay — the one-glance trend.
   *(FP&A handoff; P&L palette, regime shading optional.)*

Everything else (remaining cards, contributor tables, sector bar) is a scroll away
but still on the dashboard. Deep detail moves to dedicated routes (Section 2).

### 1.3 The nine summary cards — placement & grouping

FP&A §4 defines nine cards in two palettes. They are placed as **two visually
distinct bands** so the eye never confuses money with health:

- **Performance band (P&L palette):** Cards 1–6 — NAV, Today's P&L, Total Return,
  Alpha vs SPY (MTD), Max Drawdown, Sharpe (90d).
- **Context/Health band (status palette):** Cards 7–9 — Cash/Exposure, Market
  Regime, Simulation Health.

The two bands are separated by spacing and a subtle divider, never interleaved.

---

## SECTION 2 — NAVIGATION STRUCTURE

Flat, six-item top navigation. No nesting, no hamburger on desktop (Pi is
administered from desktop browsers per CLAUDE.md / UI Designer D). Single-user, so
no account/settings/auth surface in Phase 1.

```
[ Dashboard ] [ Portfolio ] [ Market ] [ Trades ] [ Experiments ] [ System ]
```

| Route | Question | What it shows | Primary endpoints |
|---|---|---|---|
| `/` | "How is it doing overall?" | 9 cards, NAV chart, today's trades, ranked signals, sector P&L, contributors | `portfolio/nav`, `portfolio/performance`, `algorithms/ranked`, `trades`, `market/sentiment` |
| `/portfolio` | "What do I hold and what's it worth?" | Open positions (qty, avg cost, mark, unreal. P&L), realized P&L history, NAV detail, per-symbol/sector attribution | `portfolio/positions`, `portfolio/nav`, `portfolio/performance` |
| `/market` | "What does the universe look like now?" | 50-symbol watchlist grid: last price, daily Δ, composite score, regime tag; click → per-symbol candlestick + signal series | `market/watchlist`, `market/latest`, `algorithms/ranked`, `market/bars`, `market/signal` |
| `/trades` | "What did it actually do?" | Full trade ledger, filters (date/symbol/side/sector), row → detail with the `signal_score` that triggered it | `trades`, `market/bars` |
| `/experiments` | "Which strategy version is better?" | Strategy version list, A/B return comparison, parameter diffs | *(Experiment Tracker — pending; see §5)* |
| `/system` | "Is the machine healthy?" | Per-job last-run status & times, NAV/bar/signal freshness, error log, regime history | *(job-status — pending; see §5)* |

**Default landing:** `/` (Dashboard). **Cross-links:** the Health chip links to
`/system`; the Regime chip links to `/market`; any symbol anywhere links to its
`/market?symbol=` detail; any trade row links to `/trades` detail.

---

## SECTION 3 — PAGE LAYOUTS (text wireframes)

Header and nav are a shared root layout (`+layout.svelte`) present on every route.
The Health chip and (when triggered) the broken-state banner live in this layout so
trust signals are never route-dependent.

### 3.0 Shared chrome (every route)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Autonomous Trader        NAV $101,240 ▲+0.54%   [REGIME: RISK_ON] [HEALTH:OK]│  ← header
├──────────────────────────────────────────────────────────────────────────┤
│ Dashboard │ Portfolio │ Market │ Trades │ Experiments │ System             │  ← nav
├──────────────────────────────────────────────────────────────────────────┤
│ ⚠ BANNER (only when HEALTH ≠ OK): "execute_paper_trades failed 08:00 UTC —  │
│   performance figures may be stale. → System"   [non-dismissible]           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.1 `/` — Main Dashboard

```
[PERIOD SWITCHER: ‹ Daily · WTD · MTD · YTD · Inception · 30/60/90d ›]  (drives all below)

── Performance band (P&L palette) ──────────────────────────────────────────
[CARD 1: NAV $101,240 ▲+0.54% +sparkline] [CARD 2: Today P&L ▲+$540 +0.54%]
[CARD 3: Total Return ▲+1.24%]            [CARD 4: Alpha vs SPY (MTD) ▲+0.35%]
[CARD 5: Max Drawdown −6.7%]              [CARD 6: Sharpe 90d 1.12]

── Context / Health band (status palette) ──────────────────────────────────
[CARD 7: Cash / Exposure  22% / 78%]  [CARD 8: Regime RISK_ON]  [CARD 9: Health OK]

[CHART: NAV over time — full width, SPY overlay, optional regime shading]

[TABLE: Today's ranked signals (top 10)] [TABLE: Today's trades]
   symbol · final_score · regime tag         symbol · side · qty · price · score

[BAR: Sector P&L (period)]            [LIST: Best / Worst contributors (top/bottom 5)]
```

### 3.2 `/portfolio` — Positions & Attribution

```
[HEADER reused] [PERIOD SWITCHER]

[CARD: NAV] [CARD: Cash] [CARD: Positions Value] [CARD: Realized P&L] [CARD: Unrealized P&L]

[CHART: NAV detail — full width, with cash/positions split area beneath]

[TABLE: Open positions]
  symbol │ sector │ qty │ avg cost │ mark │ mkt value │ unreal P&L $ │ unreal P&L % │ weight %

[BAR: Per-sector P&L]                 [TABLE: Per-symbol P&L (realized + unrealized, contribution %)]
```

### 3.3 `/market` — Watchlist & Per-Symbol Detail

```
[HEADER reused]
[CONTROLS: search · sort (score/Δ/symbol) · filter (sector/role: alpha·hedge·benchmark)]

[GRID/TABLE: 50-symbol watchlist]
  symbol │ name │ sector │ last │ daily Δ% │ composite score │ regime tag │ role
  (row click → detail panel / route below)

── Per-symbol detail (on selection) ────────────────────────────────────────
[HEADER: AAPL · Apple · Technology · score 78.5]
[CHART: candlestick — OHLCV from market/bars, range selector]
[CHART/STRIP: signal series — final_score & component signals over time]
[PANEL: latest indicator snapshot (data_completeness shown)]
```

### 3.4 `/trades` — Trade Ledger

```
[HEADER reused]
[FILTERS: date range · symbol · side (BUY/SELL) · sector · strategy_version]

[TABLE: trade ledger (paged, sortable)]
  fill_ts │ symbol │ sector │ side │ qty │ price │ cost basis │ realized P&L │ signal_score
  (realized P&L colored P&L palette; row click → detail)

── Trade detail (on selection) ─────────────────────────────────────────────
[PANEL: order_id · timestamps · matched lots (FIFO) · the final_score that triggered it]
[MINI-CHART: price around fill date]
```

### 3.5 `/experiments` — Strategy Comparison  *(scaffold; data pending)*

```
[HEADER reused]
[TABLE: strategy versions]  version │ active dates │ total return │ Sharpe │ max DD │ trades
[COMPARE: pick 2 versions → side-by-side returns/risk/activity + parameter diff]
[CHART: cumulative return by version (overlay)]
[EMPTY STATE: "Experiment tracking not yet wired — see Experiment Tracker handoff."]
```

### 3.6 `/system` — Health & Scheduler  *(scaffold; data pending)*

```
[HEADER reused]
[BANNER mirror: current health rollup, expanded]

[TABLE: daily job status]
  job │ scheduled (UTC) │ last run │ status │ duration │ rows written
  fetch_macro_data · fetch_news_sentiment · fetch_market_data · fetch_fundamentals
  · run_analysis · execute_paper_trades · update_portfolio_nav

[CARDS: NAV continuity · Bar freshness (% universe) · Signal coverage (mean completeness)
        · Stuck PENDING orders · Ledger reconciles?]   (all status palette)
[CHART: regime history (RISK_ON/CAUTION/RISK_OFF over time)]
[LOG: recent errors (job · time · message)]
```

---

## SECTION 4 — DATA REFRESH STRATEGY

The backend updates **once per day** (the 06:00–08:15 UTC job sequence). The
dashboard is therefore mostly displaying *yesterday's settled state* — aggressive
polling buys nothing and wastes the Pi's budget. Polling cadence is matched to how
often the underlying data can actually change.

| Surface | Cadence | Rationale |
|---|---|---|
| **Simulation Health chip + banner** | 60 s | Only fast-moving signal worth watching; user wants to catch a broken job quickly. Cheap (`/system` rollup). |
| **System page job table** | 30 s (only while `/system` is open) | Active diagnosis context; stop polling when route unmounts. |
| **Portfolio cards + NAV** | on load, then 5 min | NAV changes once/day at 08:15 UTC; 5 min guarantees freshness shortly after the snapshot without hammering. |
| **Ranked signals / today's trades** | on load, then 5 min | Written once/day by `run_analysis` / `execute_paper_trades`. |
| **Market watchlist prices** | on load, then 5 min | Phase 1 marks are daily closes from `market_bars`, **not** intraday — there is no 1-min live price to fetch. (Revisit if/when intraday data is added in Phase 2.) |
| **Candlestick / signal series (detail)** | on load + manual refresh + on range change | Historical; no value in polling. |
| **Period switcher change** | immediate refetch | User-driven, drives all cards/charts/attribution from one control (FP&A handoff). |

**Implementation guidance for the Frontend Developer:**
- Centralize polling in a small store/util keyed by surface, so cadence lives in one
  place and respects route visibility (pause polling for unmounted routes; pause on
  `document.hidden`).
- Every refetch must be **diff-tolerant**: a failed poll keeps the last good data and
  surfaces a subtle "last updated HH:MM" + retry, never a blank screen.
- **Honor the freshness contract:** when the Health surface reports not-OK, the
  performance cards must render a "data suspect" affordance (dimmed / badge), not
  silently show stale numbers (FP&A §3.1, handoff).
- No WebSockets in Phase 1 — daily-batch data does not justify a push channel; simple
  interval polling fits the Pi budget and the API's read-only `GET` surface.

---

## SECTION 5 — IMPLEMENTATION NOTES

The SvelteKit route skeleton is created alongside this document — one `+page.svelte`
per route, each a clean stub with a header comment block describing intended
contents, endpoints, and refresh cadence. **No business logic, no components, no
styling yet** — that is the Frontend Developer's job (Phase 5). The stubs establish
the route tree and the contract each page fulfills.

Files created:

```
frontend/src/routes/+page.svelte              ← main dashboard
frontend/src/routes/portfolio/+page.svelte    ← positions & attribution
frontend/src/routes/market/+page.svelte       ← watchlist & per-symbol detail
frontend/src/routes/trades/+page.svelte       ← trade ledger
frontend/src/routes/experiments/+page.svelte  ← strategy comparison (scaffold)
frontend/src/routes/system/+page.svelte       ← health & scheduler (scaffold)
```

**Not created here (flagged for Frontend Developer):**
- `frontend/src/routes/+layout.svelte` — the shared chrome (header, nav, Health chip,
  banner) described in §3.0. It must `import '$lib/styles/base.css'` once at the app
  root (UI Designer handoff). Left to the Frontend Developer because it carries real
  component logic, not just a route stub.
- SvelteKit project config (`package.json`, `svelte.config.js`, `vite.config.js`,
  `app.html`) — not yet present in `frontend/`; the Frontend Developer / DevOps own
  scaffolding the SvelteKit app shell that serves these routes as a static build
  (CLAUDE.md: SvelteKit static, served by FastAPI).

---

## Handoff notes — for Frontend Developer

**What this document produced:** the information hierarchy (trust → outcome → context
→ activity → detail), a flat six-route navigation map bound to specific API
endpoints, text wireframes for all six routes plus the shared header/nav/banner
chrome, a polling-cadence table matched to once-per-day backend updates, and the
six route-stub files.

**Build these (Phase 5), in priority order:**
1. **`+layout.svelte`** — shared header + nav + Health chip + non-dismissible
   broken-state banner (§3.0). Import `base.css` here. The Health chip polls every
   60 s and gates the banner.
2. **Dashboard (`/`)** — the two-band card row (Cards 1–6 P&L palette, 7–9 status
   palette, never interleaved), NAV chart with SPY overlay, today's signals/trades
   tables, sector P&L bar, contributors list, all driven by one period switcher.
3. **Portfolio, Market, Trades** — per §3.2–3.4.
4. **Experiments, System** — scaffold with empty states until their data sources land.

**Load-bearing rules to enforce in every component:**
- **Two color languages never mix:** `--pnl-*` for money, `--status-*` for
  health/regime (UI Designer A.1/A.2, FP&A §4). A green health chip ≠ profit.
- **Trust before numbers:** when health is not-OK, performance cards show a "data
  suspect" state; never a silent stale chart (FP&A §3.1).
- **One period control** drives all cards/charts/attribution on a page (FP&A handoff).
- **Polling respects visibility & last-good data** (§4): pause off-route / when
  hidden; never blank on a failed poll.

**Open questions / dependencies (do not block the four core routes):**
- **`/experiments`** needs the Experiment Tracker's `strategy_version` comparison
  surface — scaffold + empty state until that data/endpoint exists.
- **`/system`** needs a job-status source. `module-contracts.md` §4 exposes no
  job-status endpoint, and FP&A §3.1 / Workflow Architect flagged that a `job_runs`
  table vs logs-only is unconfirmed. Scaffold `/system` against an assumed
  `GET /api/system/health` (job table + freshness rollup) and flag it to Backend
  Architect — the Health chip in `+layout.svelte` depends on this endpoint.
- **`GET /api/market/sentiment`** still needs its `get_market_sentiment` query
  (module-contracts §4 open Q) — the Regime chip's detail consumes it; degrade
  gracefully if absent.
- **Per-symbol detail navigation** on `/market` assumes a `?symbol=` query param;
  confirm with Frontend Developer whether to use a query param or a `/market/[symbol]`
  dynamic route (either fits this IA — query param chosen here for simpler state).
