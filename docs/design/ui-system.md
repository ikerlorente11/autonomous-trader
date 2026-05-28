<!-- Agent: UI Designer | Phase: 3 | Depends on: docs/research/00-signal-synthesis.md, docs/finance/performance-metrics.md, docs/finance/reporting-structure.md -->

# Phase 3 — Dashboard Visual System

The visual language for the Autonomous Trader dashboard. This is a **dark-first, single-user financial terminal**, not a SaaS marketing app. Every decision below serves three masters: financial-domain convention (red/green, dense numerics), accessibility (WCAG AA + color-blind safety), and the Raspberry Pi performance budget (system fonts only, no web-font downloads, cheap CSS).

> **Two non-negotiable rules inherited from the upstream docs:**
> 1. **Two color languages that never mix** (`reporting-structure.md` §4): *money* uses the gain/loss (green/red) palette; *system health & regime* uses a separate status palette (ok/warn/critical). "System OK" must never visually read as "made money." Tokens are namespaced to enforce this — `--pnl-*` vs `--status-*`.
> 2. **Color is never the only cue.** Red/green color-blindness affects ~8% of men; the dashboard's whole story is red vs green. Every gain/loss element pairs color with a **sign (+/−), an arrow (▲/▼), or a shape**, so the meaning survives in grayscale.

This document defines tokens and component *specs*; the actual CSS lives in `frontend/src/lib/styles/tokens.css` (single source of truth) and `base.css` (reset + element defaults). No component code here — that is the Frontend Developer's job.

---

## A — COLOR SYSTEM

### A.1 The three semantic money colors

Financial green is **not** generic "success #10b981" green and red is **not** generic "error red." Market terminals use a slightly desaturated, slightly blue-shifted green and a warm red so the two read as a matched *pair* on a dark ground. These are tuned for AA contrast on the `--surface-base` (#0d1117) background.

| Token | Hex | Use | Contrast on `--surface-base` |
|---|---|---|---|
| `--pnl-gain` | `#26a269` | positive P&L, up bars, gains | 4.6:1 ✅ AA |
| `--pnl-gain-strong` | `#3fc380` | emphasis / hover of a gain | 6.8:1 ✅ AA |
| `--pnl-loss` | `#e5484d` | negative P&L, down bars, losses | 4.8:1 ✅ AA |
| `--pnl-loss-strong` | `#ff6166` | emphasis / hover of a loss | 6.3:1 ✅ AA |
| `--pnl-flat` | `#9aa4b2` | flat / 0.00% / unchanged | 5.9:1 ✅ AA |

Soft fills (for badge/chip backgrounds, ~12% alpha over base) avoid full-saturation blocks that vibrate on dark:

| Token | Value | Use |
|---|---|---|
| `--pnl-gain-soft` | `rgba(38, 162, 105, 0.16)` | gain badge background |
| `--pnl-loss-soft` | `rgba(229, 72, 77, 0.16)` | loss badge background |
| `--pnl-flat-soft` | `rgba(154, 164, 178, 0.14)` | flat badge background |

**Color-blind insurance:** gain/loss are *always* shown with `+`/`−` and `▲`/`▼`. The green/red are additionally distinguishable by lightness (loss is rendered slightly brighter at `-strong`), helping deuteranopes who lose hue but keep luminance. A future user-toggle for a blue/orange palette is noted in Handoff (deferred).

### A.2 Status palette (health & regime — SEPARATE from money)

Drives Simulation Health (card 9) and Market Regime (card 8) per `reporting-structure.md` §3/§4. Deliberately **teal/amber/magenta-red**, not the P&L green/red, so a healthy system never looks like a profit.

| Token | Hex | Meaning | Maps to |
|---|---|---|---|
| `--status-ok` | `#2dd4bf` (teal) | jobs green / RISK_ON | health OK, regime RISK_ON |
| `--status-warn` | `#f5a623` (amber) | degraded / CAUTION | health degraded, regime CAUTION |
| `--status-critical` | `#d6409f` (magenta-red) | broken / RISK_OFF | health broken, regime RISK_OFF |
| `--status-ok-soft` | `rgba(45, 212, 191, 0.16)` | chip bg |  |
| `--status-warn-soft` | `rgba(245, 166, 35, 0.16)` | chip bg |  |
| `--status-critical-soft` | `rgba(214, 64, 159, 0.16)` | chip bg |  |

> Teal/amber/magenta is intentionally a *different hue triad* from green/red so the two systems are separable even side by side and even for color-blind users. RISK_OFF being magenta (not the loss-red) prevents "the market is defensive" from being misread as "we lost money."

### A.3 Surface hierarchy (dark theme)

GitHub-dark-derived neutral ramp — proven for dense data UIs and easy on the Pi (flat fills, no gradients). Elevation is expressed by *lightness steps*, not heavy shadows.

| Token | Hex | Role |
|---|---|---|
| `--surface-base` | `#0d1117` | app background (deepest) |
| `--surface-raised` | `#161b22` | card background |
| `--surface-overlay` | `#1c2330` | elevated card / popover / hover row |
| `--surface-overlay-2` | `#242c3a` | modal / dropdown menu (top layer) |
| `--surface-inset` | `#0a0e14` | wells: chart plot area, code/log blocks |
| `--border-subtle` | `#262d38` | card borders, table row dividers |
| `--border-strong` | `#3a4452` | focused/active borders, separators |

### A.4 Text colors

| Token | Hex | Use | Contrast on `--surface-raised` |
|---|---|---|---|
| `--text-primary` | `#e6edf3` | headings, primary numbers | 13.4:1 ✅ AAA |
| `--text-secondary` | `#aeb9c7` | body, secondary numbers | 7.6:1 ✅ AAA |
| `--text-muted` | `#7d8896` | labels, captions, axis ticks | 4.6:1 ✅ AA |
| `--text-disabled` | `#525b67` | disabled (non-essential only) | 2.4:1 (decorative) |
| `--text-on-accent` | `#0d1117` | text on a filled accent/gain/loss button | — |

### A.5 Brand accent (non-financial UI: links, focus, active nav)

A calm blue that is **not** confusable with gain-green or status-teal. Used for interactive affordances only — never for data values.

| Token | Hex | Use |
|---|---|---|
| `--accent` | `#4c8dff` | links, primary buttons, active nav, selection |
| `--accent-strong` | `#6ba1ff` | hover |
| `--accent-soft` | `rgba(76, 141, 255, 0.16)` | active-row tint, focus glow |
| `--focus-ring` | `#6ba1ff` | keyboard focus outline (2px, 2px offset) |

### A.6 Chart / multi-series palette

For the NAV-vs-benchmark line chart, sector bars, and any multi-line view. Portfolio and benchmark get **fixed, semantically reserved** colors so they're recognizable across every screen; the categorical ramp is for ad-hoc series (e.g. multiple positions). All AA-legible as 2px lines on `--surface-inset`.

| Token | Hex | Reserved meaning |
|---|---|---|
| `--chart-portfolio` | `#4c8dff` (accent blue) | the portfolio NAV line — always |
| `--chart-benchmark` | `#9aa4b2` (neutral) | SPY benchmark line — always, dashed |
| `--chart-grid` | `#21272f` | gridlines (low-contrast, behind data) |
| `--chart-axis` | `#7d8896` | axis labels / ticks (= `--text-muted`) |
| `--chart-series-1` | `#4c8dff` | categorical 1 |
| `--chart-series-2` | `#2dd4bf` | categorical 2 |
| `--chart-series-3` | `#f5a623` | categorical 3 |
| `--chart-series-4` | `#a78bfa` | categorical 4 |
| `--chart-series-5` | `#f471b5` | categorical 5 |
| `--chart-series-6` | `#56d364` | categorical 6 |

> Portfolio = solid blue, benchmark = **dashed** neutral: the solid-vs-dashed distinction means the NAV chart is readable without relying on color (color-blind safe by construction).

### A.7 Candlestick palette

Uses the same gain/loss hue family but with distinct tokens so a charting lib can be themed independently (and so candle bodies can be tuned without touching badge colors). The up/down distinction is reinforced by **body fill** (down = filled, up = hollow/outlined) per classic OHLC convention — again, not color-only.

| Token | Hex | Use |
|---|---|---|
| `--candle-up-body` | `#26a269` | up candle body (hollow: stroke this, fill `--surface-inset`) |
| `--candle-up-wick` | `#3fc380` | up candle wick/border |
| `--candle-down-body` | `#e5484d` | down candle body (solid fill) |
| `--candle-down-wick` | `#ff6166` | down candle wick/border |
| `--candle-volume-up` | `rgba(38, 162, 105, 0.35)` | volume bar on up day |
| `--candle-volume-down` | `rgba(229, 72, 77, 0.35)` | volume bar on down day |

---

## B — TYPOGRAPHY

### B.1 Font stacks (system only — zero web-font downloads, Pi-friendly)

| Token | Stack | Use |
|---|---|---|
| `--font-sans` | `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` | all UI text, labels, headings |
| `--font-mono` | `ui-monospace, "SF Mono", "Cascadia Mono", "Roboto Mono", Consolas, "Liberation Mono", monospace` | **all prices, quantities, P&L, %, dates** |

**Rule:** every numeric value that should align in columns or update in place (prices, NAV, %, qty, ratios) uses `--font-mono` **with `font-variant-numeric: tabular-nums`** so digits are fixed-width — numbers don't jitter as they tick and columns line up. `base.css` applies tabular figures by default to a `.num` utility and to `<td>`/`<code>`.

### B.2 Size scale (rem, 16px root)

| Token | Size | px | Use |
|---|---|---|---|
| `--text-3xl` | 2.25rem | 36 | hero portfolio NAV value |
| `--text-2xl` | 1.75rem | 28 | card primary numbers (Today's P&L, Total Return) |
| `--text-xl` | 1.375rem | 22 | section headings |
| `--text-lg` | 1.125rem | 18 | card titles, sub-numbers |
| `--text-base` | 1rem | 16 | body, table cells |
| `--text-sm` | 0.875rem | 14 | secondary table data, dense rows |
| `--text-xs` | 0.75rem | 12 | labels, badges, axis ticks |
| `--text-2xs` | 0.6875rem | 11 | captions, "n settled signals", timestamps |

### B.3 Weights & line-height

| Token | Value | Use |
|---|---|---|
| `--weight-regular` | 400 | body |
| `--weight-medium` | 500 | labels, table headers, chips |
| `--weight-semibold` | 600 | card titles, emphasized numbers |
| `--weight-bold` | 700 | hero NAV value only |
| `--leading-tight` | 1.15 | large numbers |
| `--leading-normal` | 1.5 | body / paragraphs |

> Large numbers (NAV, P&L) are `--weight-semibold`/`bold` + `--leading-tight`; labels above them are `--text-xs`, `--weight-medium`, `--text-muted`, uppercase with `letter-spacing: 0.04em` — the classic "small caps label over a big number" terminal pattern.

---

## C — COMPONENT SPECIFICATIONS (visual specs, not code)

### C.1 Price-change badge (±% with color)

- **Anatomy:** `[▲ +1.24%]` — directional glyph + sign + value, in `--font-mono` tabular.
- **Gain:** text `--pnl-gain`, bg `--pnl-gain-soft`, glyph `▲`, sign `+`.
- **Loss:** text `--pnl-loss`, bg `--pnl-loss-soft`, glyph `▼`, sign `−` (true minus U+2212, fixed width).
- **Flat (|Δ| < 0.005%):** text `--pnl-flat`, bg `--pnl-flat-soft`, glyph `▬` (or em-dash), no sign.
- Padding `--space-1` / `--space-2`, radius `--radius-sm`, size `--text-xs`/`--text-sm`, weight `--weight-medium`.
- **Three redundant cues (color + sign + glyph)** = color-blind safe. Never ship a bare colored number.

### C.2 Portfolio value card (large number + sparkline)

- **Layout (top-down):** uppercase muted label ("PORTFOLIO VALUE") → hero value `--text-3xl` mono semibold `--text-primary` → daily-change badge (C.1) inline → a thin **sparkline** spanning the card width at the bottom.
- Card: `--surface-raised`, `--border-subtle`, `--radius-lg`, padding `--space-5`.
- **Sparkline** colored by the *period's* net direction (gain-green / loss-red), 1.5px stroke, no axes, ~32–40px tall, plotted on transparent ground. If a benchmark sparkline overlays, it's the dashed neutral `--chart-benchmark`.
- A `stale_marks` / suspect-data state (per `reporting-structure.md` §1.1 / §3) dims the value to `--text-secondary` and shows a small `--status-warn` dot + "stale" caption — never a blank or silently-wrong number.

### C.3 Trade-status chip (FILLED / PENDING / REJECTED)

Order lifecycle status is **operational state, not money** → it uses a small dedicated chip vocabulary (closer to the status palette family, kept distinct from regime/health).

| Status | Text/dot color | Bg | Glyph |
|---|---|---|---|
| `FILLED` | `--pnl-flat` (neutral-positive, settled) / dot `--status-ok` | `--surface-overlay` | ● filled dot |
| `PENDING` | `--status-warn` | `--status-warn-soft` | ◐ half / spinner |
| `REJECTED` | `--status-critical` | `--status-critical-soft` | ✕ |
| `CANCELLED` | `--text-muted` | `--surface-overlay` | ⊘ |

- Shape: pill, `--radius-pill`, `--text-xs`, `--weight-medium`, uppercase, leading status dot/glyph (cue beyond color).
- `PENDING` after NAV time is a bug per FP&A §3.1 — Frontend should still render it but the Health banner owns the alert.

### C.4 Signal-strength indicator (0–100 score)

Aligned to the synthesis `final_score` model (00-signal-synthesis §3): a 0–100 composite that ranks the universe; names above a config cutoff are buy candidates. The indicator must convey **(a) the magnitude** and **(b) the actionable band**.

- **Form:** a horizontal segmented meter (0→100) with the score numerically labeled (`--font-mono` tabular). Above it, a small directional/action tag matching `algorithm_signals.action` (BUY / HOLD / SELL).
- **Bands (encoded by fill + a band label, not color alone):**
  - `0–40` **weak** → fill `--pnl-flat`, no action emphasis.
  - `40–60` **neutral** → fill `--text-muted`.
  - `60–80` **strong** → fill `--pnl-gain`.
  - `80–100` **very strong** → fill `--pnl-gain-strong`, optional ▲▲ marker.
- **`data_completeness` (synthesis §3.3) is surfaced**, not hidden: render a faint secondary tick or a "92% data" caption so a high score on thin data is visibly qualified. A low-completeness score shows a `--status-warn` hairline.
- For *negative/avoid* signals (SELL action / score driving exits) mirror to the loss side with `--pnl-loss`. The numeric label + BUY/HOLD/SELL word is the non-color cue.

### C.5 Market-status indicator (open / closed / pre-market / after-hours)

- **Form:** small pill with a leading dot + label, `--text-xs` mono for any countdown.
  - `OPEN` → dot `--status-ok` (pulsing 2s ease, respects `prefers-reduced-motion` → static), label "MARKET OPEN".
  - `PRE-MARKET` / `AFTER-HOURS` → dot `--status-warn`, label + session name.
  - `CLOSED` → dot `--text-muted`, label "MARKET CLOSED" + next-open time.
- This is **session state, not regime** — keep it visually lighter than the Regime chip (card 8) so they don't compete. Distinct dot colors + always-present text label = non-color-reliant.

### C.6 Regime & health chips (cards 8 & 9)

- **Regime chip:** `RISK_ON` (`--status-ok`) / `CAUTION` (`--status-warn`) / `RISK_OFF` (`--status-critical`), pill with leading dot + uppercase label. Placed adjacent to the return cards per FP&A §3.2 so "flat NAV in RISK_OFF" reads as *correct behavior*, not a break.
- **Health chip / banner:** OK / DEGRADED / BROKEN on the same status palette. When not all-green, a **non-dismissible top banner** (`--surface-overlay` bg, `--status-warn`/`--status-critical` left border 3px) states "data suspect" — performance cards must not silently show stale numbers (FP&A §3.1).

### C.7 Threshold coloring of metric cards

Metric values (Sharpe, drawdown, profit factor) color against `PerformanceThresholds` (performance-metrics §4): good → `--pnl-gain`, warn → `--status-warn`, bad/breach → `--pnl-loss`. `nan` renders as an em-dash `—` in `--text-muted` (never blank). Because warn uses the *status* amber while good/bad use the *money* palette, a "warn" metric is unmistakably a caution, not a small loss.

---

## D — LAYOUT GRID

### D.1 Spacing & radius scale (4px base)

| Token | Value | | Token | Value |
|---|---|---|---|---|
| `--space-1` | 4px | | `--radius-sm` | 4px |
| `--space-2` | 8px | | `--radius-md` | 8px |
| `--space-3` | 12px | | `--radius-lg` | 12px |
| `--space-4` | 16px | | `--radius-pill` | 999px |
| `--space-5` | 24px | | | |
| `--space-6` | 32px | | **Elevation** | |
| `--space-8` | 48px | | `--shadow-card` | `0 1px 2px rgba(0,0,0,0.4)` |
| `--space-10` | 64px | | `--shadow-overlay` | `0 8px 24px rgba(0,0,0,0.5)` |

Shadows are minimal — on dark, elevation is carried mostly by the surface-lightness ramp (A.3), which is cheaper to render than large blurs on the Pi.

### D.2 Grid system

A **12-column fluid grid** inside a max-width container. Desktop is primary (Pi is administered from desktop browsers per CLAUDE.md), but the layout must stay usable down to phone width.

| Token | Value |
|---|---|
| `--container-max` | 1440px |
| `--grid-cols` | 12 |
| `--grid-gap` | `--space-4` (16px) |
| `--page-pad-x` | `--space-6` desktop / `--space-4` mobile |

### D.3 Breakpoints (mobile-first)

| Token | Min width | Layout behavior |
|---|---|---|
| (base) | 0 | **1 column.** Cards stack full-width; tables become horizontally scrollable; period switcher collapses to a `<select>`. |
| `--bp-sm` | 640px | **2-column** card row; sparklines visible. |
| `--bp-md` | 900px | **3-column** card grid; NAV chart full-width below cards; nav becomes a sidebar-or-topbar. |
| `--bp-lg` | 1200px | **Full dashboard:** the 9-card hero strip wraps in 3×3 or a single dense row; NAV chart + side panel (regime/health, contributors) side-by-side. |
| `--bp-xl` | 1440px | container capped; extra width becomes margin (no further reflow). |

### D.4 Above-the-fold composition (maps to FP&A §4)

Reading order desktop, top → bottom:
1. **Top bar:** app title, period switcher (Daily/WTD/MTD/YTD/Inception + 30/60/90), market-status indicator (C.5), regime chip (C.6).
2. **Health banner** (only when not all-green).
3. **Hero strip:** Portfolio Value card (C.2, wider) + the other money cards (Today's P&L, Total Return, Alpha, Max DD, Sharpe) — P&L palette.
4. **Context row:** Cash/Exposure, Regime, Simulation Health — status palette (visually separated from row 3 by a divider/heading so the two palettes never blur together).
5. **NAV chart** (portfolio solid blue + benchmark dashed neutral, optional regime shading).
6. **Below fold:** Best/Worst contributors, Sector P&L bar, trades table, signal-quality views.

Touch targets ≥ 44px on mobile; tables keep ≥ 44px row height on touch widths.

---

## Handoff notes

**For the Frontend Developer**

*What I produced — three files:*
- `docs/design/ui-system.md` (this doc) — the spec.
- `frontend/src/lib/styles/tokens.css` — **the single source of truth.** Every color, surface, text size, weight, spacing, radius, shadow, breakpoint, and chart/candle color is a CSS custom property on `:root`. Consume these; do not hardcode hex/px in components.
- `frontend/src/lib/styles/base.css` — modern reset + element defaults (body uses `--surface-base` + `--text-primary` + `--font-sans`; numeric defaults apply `tabular-nums`). It `@import`s `tokens.css`, so importing `base.css` alone pulls everything.

*How to wire it up:* import `base.css` once at the app root (e.g. in the root `+layout.svelte`): `import '$lib/styles/base.css';`. `base.css` imports `tokens.css` for you. The dashboard is dark-only for Phase 1, so tokens live on `:root` (no `[data-theme]` switch needed yet).

*Token naming conventions (so you pick the right one):*
- `--pnl-*` = **money** (gain/loss/flat). `--status-*` = **health & regime** (ok/warn/critical). **Never cross these** — this is the load-bearing UX rule from FP&A §4.
- `--surface-*` = backgrounds (base→raised→overlay→overlay-2), `--border-*`, `--text-*` (primary/secondary/muted/disabled).
- `--accent-*` = interactive chrome only (links/buttons/focus), never data.
- `--chart-*` (portfolio reserved blue solid, benchmark reserved neutral dashed) and `--candle-*`.
- `--font-*`, `--text-*` (sizes), `--weight-*`, `--leading-*`; `--space-*`, `--radius-*`, `--shadow-*`, `--bp-*`.

*Two rules to enforce in every component:*
1. Every gain/loss element carries a **sign and/or arrow/shape**, not color alone (C.1) — color-blind + grayscale safe.
2. `nan` → `—`; stale/suspect data → visible `--status-warn` cue, never blank or silently stale (per performance-metrics §1 & FP&A §3).

**Open questions / deferred decisions:**
- **Alternative (blue/orange) palette toggle** for color-blind users: deferred. The sign+arrow+shape redundancy already meets AA without it; a user toggle is a low-cost Phase-1.5 add if requested.
- **Light theme:** out of scope for Phase 1 (dashboard is dark-only). Tokens are structured so a `[data-theme="light"]` block can override later without renaming anything.
- **Charting library choice** (lightweight-charts vs uPlot vs custom SVG) is the Frontend Developer's call — tokens are library-agnostic, but I recommend a canvas/SVG lib that accepts CSS-variable colors and is ARM64/Pi-light. `--chart-*`/`--candle-*` are named to map cleanly onto candlestick-lib theme options.
- **Regime shading on the NAV chart** (FP&A §4 "if cheap") is optional; if implemented, use `--status-*-soft` band fills behind the data.
