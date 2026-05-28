<!-- Agent: Frontend Developer | Phase: 5 | Depends on: UI Designer, UX Architect, Software Architect (module-contracts), Financial Analyst, FP&A Analyst -->

# Phase 5 — Frontend Implementation

The SvelteKit dashboard: full project scaffolding, a typed API client bound to the
**live** backend, shared components, and all seven routes. Built with Svelte 5 runes
(`$state`/`$derived`/`$effect`/`$props`), served as a static build by FastAPI
(`@sveltejs/adapter-static`, no SSR), dark-only, single-user, read-only — per CLAUDE.md.

> **Source-of-truth note.** The launch brief's assumed API shapes differed from what
> the backend actually serves. I treated the **live router/schema code as authoritative**
> (`backend/api/routers/*.py`, `backend/api/schemas.py`, `backend/contracts.py`) and
> `module-contracts.md` as the contract only where no code exists. The client types
> mirror the live shapes exactly. Deviations from the brief are listed below.

---

## 1. Scaffolding

| File | Purpose |
|---|---|
| `frontend/package.json` | Svelte 5, SvelteKit 2, `@sveltejs/adapter-static`, `chart.js`, `chartjs-chart-financial`, `chartjs-adapter-date-fns`, `date-fns`, `vite`, `typescript`, `svelte-check` |
| `frontend/svelte.config.js` | adapter-static, `fallback: index.html` (SPA) so `/market/[symbol]` resolves at runtime. Static routes prerender their shell (`+layout.ts` `prerender=true`); the dynamic `/market/[symbol]` route is `prerender=false` and served via the SPA fallback |
| `frontend/vite.config.ts` | SvelteKit plugin + dev proxy `/api → http://localhost:8000` |
| `frontend/tsconfig.json` | strict TS, extends `.svelte-kit/tsconfig.json` |
| `frontend/.npmrc`, `frontend/src/app.html`, `frontend/src/app.d.ts` | app shell + ambient types; `app.html` sets `data-theme="dark"` |
| `frontend/static/favicon.svg` | inline SVG mark |
| `frontend/src/routes/+layout.ts`, `+page.ts` | `ssr=false`, `prerender=false` (static + client fetch) |

**Styles wiring:** `+layout.svelte` imports `tokens.css` → `base.css` → `aliases.css` → `table.css`.
`tokens.css` (UI Designer, single source of truth) is **never modified**. `aliases.css`
is the only bridge: it maps the shorter names components use (`--color-bg-2`,
`--color-gain`, `--radius-full`, …) onto canonical tokens (`--surface-raised`,
`--pnl-gain`, `--radius-pill`, …). The two color languages are preserved in the bridge:
money names → `--pnl-*`, status/chrome names → `--status-*`/`--accent`.

---

## 2. API client design (`frontend/src/lib/api/`)

- **`client.ts`** — one `request<T>()` wrapping `fetch('/api/...')`. Uniform `ApiError`
  (`code`, `message`, `status`). Parses both a custom `{error:{code,message}}` envelope
  and FastAPI's `{detail}`. 404 → `code:'NOT_FOUND'` so pages can detect "not wired yet."
  Accepts an injectable `fetcher` (SvelteKit `load`-compatible) though all calls are
  currently client-side.
- **`types.ts`** — TypeScript mirrors of the live DTOs. Decimals arrive as **strings**
  (Decimal-safe JSON); every consumer parses via `toNum()`. Documented against the exact
  source file/class.
- **`endpoints.ts`** — thin typed wrappers per domain. UI range presets
  (`7d/30d/90d/1y/all`, `30d/90d/1y`) are translated to backend `start`/`end` ISO
  datetimes (`rangeWindow`), since the backend takes datetimes, not range strings.
- **`index.ts`** — barrel re-export.

**Live endpoint map actually used:**

| UI call | Backend route | Response |
|---|---|---|
| `portfolioApi.summary` | `GET /api/portfolio/summary` | `PortfolioSummary` |
| `portfolioApi.positions` | `GET /api/portfolio/positions` | `Position[]` |
| `portfolioApi.nav(range)` | `GET /api/portfolio/nav?start&end` | `PortfolioSnapshot[]` |
| `portfolioApi.performance` | `GET /api/portfolio/performance` | `PerformanceMetrics` (`returns/risk/trades` float dicts) |
| `marketApi.watchlist` | `GET /api/market/watchlist` | `WatchlistEntry[]` |
| `marketApi.bars(sym,range)` | `GET /api/market/bars/{symbol}?start&end` | `OHLCVBar[]` |
| `tradesApi.list(filters)` | `GET /api/trades?symbol&start&end&limit` | `TradeRecord[]` |
| `algorithmsApi.signals(limit)` | `GET /api/algorithms/signals?limit` | `SignalEntry[]` |
| `algorithmsApi.experiments` | `GET /api/algorithms/experiments` | `ExperimentEntry[]` |
| `systemApi.status` | `GET /api/system/status` | `SystemStatus` |

---

## 3. Shared components (`frontend/src/lib/components/`, `…/charts/`)

`PriceChange` (color + sign + arrow, color-blind safe), `MetricCard` (value + label +
good/warn/bad band), `SignalScore` (0–100 bar, banded fill), `StatusBadge`
(FILLED/PENDING/REJECTED/BUY/SELL/HOLD/success/failed/running…), `LoadingSpinner`,
`ErrorState` (with retry), `EmptyState`, `Skeleton`, `Card` (titled panel + actions
snippet + span), `RangeSelector`, `Icon` (inline SVG nav icons), and **`Region`** — a
generic `{#snippet}`-driven wrapper that renders loading/empty/error/`notReadyOn404`
states uniformly so every page handles all states without boilerplate.

**Charts:** `ChartCanvas` (Chart.js lifecycle: rebuilds on `config` change, `destroy()`
on unmount), `register.ts` (one-time controller registration incl. financial
candlestick/OHLC), `theme.ts` (reads CSS tokens from the DOM → Chart.js colors),
`NavChart` (portfolio solid blue + SPY dashed neutral, time axis), `CandlestickChart`
(candles + optional MA20/MA50 toggle), `VolumeChart` (up/down dimmed bars).

**Utils:** `format.ts` (`money`, `percent`, `percentFrac` for fractions, `num`,
`changeClass`, `arrow`, date/relative-time, `toNum` defensive parse), `thresholds.ts`
(metric bands per performance-metrics §4, evaluated on **fractions**; labels/tooltips),
`poller.svelte.ts` (`createResource`: stale-while-revalidate, keeps last-good data on
error, interval poll, auto-clears on `onDestroy`, pauses when `document.hidden`).

---

## 4. Routes (7)

1. **`/`** — hero (total value, today's Δ derived from last two NAV points, total P&L,
   cash·invested); KPI cards (Sharpe, Max Drawdown, Win Rate, Open Positions); NAV-vs-SPY
   chart (30d); top 5 signals; recent 10 trades.
2. **`/portfolio`** — summary strip; full performance-metrics grid (returns/risk/trades
   groups per performance-metrics §3); NAV chart with 7d/30d/90d/1y/all selector;
   positions table (market value + weight derived client-side since the backend `Position`
   omits them).
3. **`/market`** — watchlist table (symbol, sector, last close, action, score) with sector
   filter + sortable columns; row → `/market/[symbol]`.
4. **`/market/[symbol]`** — 90d candlestick (range selector + MA toggle) + volume; signal
   panel sourced from the watchlist entry (no per-symbol score endpoint exists);
   per-symbol trades.
5. **`/trades`** — filters (symbol/date-range server-side; side client-side); ledger with
   computed total; expandable row showing the triggering `reason`.
6. **`/experiments`** — runs table from `/api/algorithms/experiments`; select ≤2 for a
   config side-by-side; explicit notice that the metrics comparison surface is not wired.
7. **`/system`** — health rollup (status palette), daily-jobs table (status/last/duration/
   next), recent errors; reads the shared 30s poller.

---

## 5. Routing decision: `/trades` vs `/history`

Kept **`/trades`**. The UX doc (§2, §3.4) names the route `/trades`, and the route
skeleton shipped by the UX Architect is `frontend/src/routes/trades/+page.svelte`
(there is no `history/` directory). The page covers all trades-table requirements
(filterable ledger + per-trade triggering reason).

---

## 6. Not-yet-built / partial backends

- **`/api/system/status` exists** (contrary to the brief) and returns
  `{server_time, jobs[], recent_errors[]}`. The `/system` page and the header health dot
  consume it. If it ever fails/404s, `systemStatus.available=false` → header shows
  "System offline" and `/system` shows a retryable error. Data-freshness-per-symbol and
  NAV-continuity (ux §3.6) are **not** exposed; the page states this rather than faking it.
- **Experiments**: `/api/algorithms/experiments` returns run *metadata only* (no metrics
  envelope). The page renders runs + config compare and explicitly says performance
  comparison is pending the Experiment Tracker surface. `notReadyOn404` degrades cleanly
  if the route is absent.
- **No per-symbol signal-breakdown endpoint** (`module-contracts` lists `/market/signal`
  for a single indicator series, not a category breakdown). The symbol page surfaces the
  watchlist composite score/action instead of fabricating sub-scores.

---

## 7. Polling design

Centralized in `createResource` (per-resource interval, visibility-aware, last-good-data
retention) and one shared `systemStatus` store. Cadence follows ux §4 (daily-batch data):

| Surface | Cadence |
|---|---|
| System health (header dot + `/system`) | 30 s, shared single poller, paused when hidden |
| Portfolio cards / NAV / signals / trades | 5 min |
| Market watchlist | 60 s during US market hours, else 5 min (`marketHours.ts`; Phase-1 marks are daily closes so this only governs UI refresh cadence) |
| Candlestick / per-symbol | on load + on range/symbol change (no polling) |

All intervals clear on unmount (`onDestroy` in the resource; `stopSystemPolling` available).
No WebSockets (ux §4).

---

## 8. Deviations from the docs (and why)

1. **API shapes** follow live code, not the brief's assumed shapes (see §2). Money values
   are strings, not numbers; `/positions` has no market_value/weight/pnl% (derived in UI);
   `/performance` is three float dicts, not flat fields; signals endpoint is
   `/algorithms/signals` not `/top-signals`.
2. **Metric bands** evaluate on **fractions** (Sharpe 1.12, max_dd −0.067, win_rate 0.55)
   because `summarize_performance` emits fractions (performance-metrics §1/§3).
3. **Period switcher**: implemented as a NAV **range** selector (7d…all) on dashboard/
   portfolio rather than the full Daily/WTD/MTD/YTD/Inception switcher, because the live
   API exposes `nav?start&end` and `performance` (no period-bucketed endpoint). Flagged
   for a future period endpoint.
4. **`aliases.css`** added so components reference stable short names without editing the
   UI Designer's `tokens.css`. No new colors invented — pure aliases.

---

## Handoff notes — for the Analytics Reporter

**What I produced:** full SvelteKit scaffold, typed API client bound to the live
backend, shared component + chart library, all 7 routes, and this doc.

**Verify these data-flow / KPI checkpoints (scheduler → DB → API → UI):**
- **Header NAV** = `/api/portfolio/summary.total`; **Today's Δ** is computed in the UI from
  the last two `/portfolio/nav` points — confirm it matches `NAV_t − NAV_{t-1}` once NAV
  rows exist.
- **Dashboard KPIs** map to `/performance`: Sharpe=`risk.sharpe`, Max DD=`risk.max_drawdown`
  (fraction → %), Win Rate=`trades.win_rate`. Open Positions=`summary.positions_count`.
- **Positions market value + weight are UI-derived** (qty×price); verify against any
  server-side truth the Analytics layer adds.
- **Metric coloring** uses performance-metrics §4 thresholds — confirm bands match.
- **NAV chart** draws the SPY benchmark only when `benchmark_value` is present; verify the
  benchmark column is populated.
- **/system** reflects `JOB_SCHEDULE`; confirm the 4 live jobs (fetch_market_data,
  run_analysis, execute_paper_trades, update_portfolio_nav) appear with sensible
  last/next run times.

**Known gaps (not bugs):**
- Experiments performance comparison and per-symbol category breakdown await backend
  surfaces; pages degrade gracefully and say so.
- Period-over-period switcher is a range selector pending a period endpoint.
- Data-freshness-per-symbol on `/system` awaits an endpoint.

**Build status:** verified. `npm install` + `npm run build` succeed and
`npx svelte-check` reports **0 errors, 0 warnings** (350 files). Stack pinned to
SvelteKit 2.61, Svelte 5.55, vite-plugin-svelte 4, Vite 5.4, adapter-static 3.0,
chart.js 4.4 + chartjs-chart-financial 0.2 + chartjs-adapter-date-fns 3, plus
`@types/node` (dev). Static output lands in `frontend/build/` (7 prerendered route
shells + `index.html` SPA fallback + hashed `_app/` assets), which FastAPI's
`StaticFiles(html=True)` mount in `backend/api/main.py` serves at `/`.

A minimal `frontend/src/lib/charts/financial.d.ts` supplies the missing
chartjs-chart-financial typings and augments Chart.js's `ChartTypeRegistry` with
`candlestick`/`ohlc`; `date-adapter.d.ts` declares the untyped date adapter.
The dashboard could not be exercised against live data (no running backend in this
environment); all pages were verified to compile, prerender, and render their
loading/empty/error states (all 7 routes return HTTP 200 from `npm run preview`).

**Chart SSR note:** `/` and `/portfolio` prerender (`+layout.ts prerender=true`) and
import chart components. `chartjs-chart-financial` touches Chart.js internals at
module-eval time and throws under Node, so Chart.js + the financial plugin + the date
adapter are loaded **lazily** via `register.ts::loadChart()` (an async dynamic import
called only from `ChartCanvas`'s browser-side build effect). Static top-level imports of
those libs must never be reintroduced or prerender will 500.
