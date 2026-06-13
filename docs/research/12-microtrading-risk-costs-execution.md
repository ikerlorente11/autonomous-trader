<!-- Agent: Financial Analyst | Phase: 0-micro | Depends on: docs/research/00-signal-synthesis.md, docs/finance/performance-metrics.md -->

# Phase 0-micro — Microtrading: Risk Management, Transaction-Cost Economics, Session/Calendar Effects & Micro-Specific Metrics

**Stream:** the day-trading equivalent of the macro/risk/calendar stream (`03-macro-intermarket-calendar.md`). This document does **not** pick the micro entry signals (that is a sibling stream); it answers the four questions that decide whether a same-day "microinversiones diarias" sleeve can survive at all: *(1) do the costs eat the edge? (2) what risk rails stop it blowing up? (3) when in the session should it trade or stand aside? (4) how do we even measure it?*

> **Scope & constraints inherited from CLAUDE.md.** Phase 1 is **simulation only** — every rule here is a paper-trading rule against the `PaperBroker`. The **`BrokerAdapter` seam is sacred**: every micro entry and every micro exit goes through `place_order(symbol, side, qty: Decimal, order_type)` exactly like `protective_sell` already does — no new broker method, no direct broker call from a job. **Nothing is hardcoded**: every number below is a named `config/strategy.yaml` knob (proposed `micro.*` namespace), version-overlayable exactly like the existing strategy versions. The **P10 commission model is GLOBAL and already live** — micro trades pay it on every fill (`COMMISSION_PCT × notional + COMMISSION_PER_ORDER`, stored on `trade_orders.commission`). The **Pi 4 / 4GB budget** is the binding physical constraint and is flagged at every point a micro loop threatens it.

> **The honest headline, stated up front (the verdict the owner asked for):** at the project's *default* commission config (`COMMISSION_PCT=0`, `COMMISSION_PER_ORDER=0`) **microtrading looks free and isn't** — the real cost is the **bid/ask spread + slippage**, which the simulator does not yet model and which, for a same-day round trip, is the dominant tax. With a **realistic retail-equity assumption (≈2–5 bps spread per side)** the break-even move is **~0.05–0.15%**, and once a non-zero commission is switched on it climbs fast. A micro strategy is only viable if its **expected gross per-trade edge clears that break-even with margin AND its win rate × average win covers the cost drag of high turnover**. Most naïve "scalp every wiggle" ideas fail this test. The recommendation is to ship microtrading **behind a realistic cost model first** (so the backtester tells the truth), with hard turnover caps. Details below.

---

## SECTION 1 — TRANSACTION-COST ECONOMICS OF MICROTRADING

The single most important fact about day-trading: **you pay the round-trip cost on every trade, but you only collect the edge if the move happens.** At swing horizons (1–4 weeks, synthesis §0) a 3–8% expected move dwarfs a few bps of cost. At intraday horizons the expected move per trade is **tens of basis points**, so the same few bps of cost is now a large fraction of the edge. Costs scale with **turnover**; edge does not.

### 1.1 The three cost components of a round trip

| Component | What it is | In the simulator today | Phase-2 reality |
|---|---|---|---|
| **Commission** | `COMMISSION_PCT × notional + COMMISSION_PER_ORDER` per fill (P10) | **Modeled** (default 0/0), stored on `trade_orders.commission`, subtracted by `compute_cash` | Many US retail brokers $0; EU brokers often per-order (€1–€5) or %. |
| **Bid/ask spread** | You buy at the ask, sell at the bid; half-spread per side | **NOT modeled** — `PaperBroker` fills at the bar price | The dominant micro cost. Liquid large-caps ≈ 1–3 bps; small/illiquid 10–50+ bps. |
| **Slippage / market impact** | Price moves against you between decision and fill; your own order pushes it | **NOT modeled** (backtester fills at next open ± a slippage knob) | Worsens with size, volatility (high VIX), and thin sessions. |

> **The simulation-only gap to flag loudly:** with the **default** P10 config the `PaperBroker` is **frictionless** (`performance-metrics.md` §4 already notes trip P&L is gross). A frictionless intraday backtest will report fantasy profits because **the spread — the real micro tax — is invisible.** A micro sleeve must **not** be evaluated against the default cost model. See §6 for the minimum cost config to switch on before any micro version is judged.

### 1.2 Break-even math (worked through)

Define for one round trip on notional `N`:

```
round_trip_cost($) =  2 × (COMMISSION_PCT × N)        # commission, both legs (P10)
                    +  2 × COMMISSION_PER_ORDER         # per-order, both legs (P10)
                    +  spread_bps/10000 × N             # full spread = half per side × 2 sides
                    +  slippage_bps/10000 × N           # round-trip slippage assumption
```

Break-even gross move (as a fraction of price) is the cost expressed in bps of notional:

```
breakeven_move_pct  =  round_trip_cost($) / N
                    =  2 × COMMISSION_PCT
                    +  2 × COMMISSION_PER_ORDER / N
                    +  (spread_bps + slippage_bps) / 10000
```

The per-order term is the one that **explodes at small ticket size** — it is a *fixed* cost divided by notional.

#### Worked example A — project default commission (0/0) + realistic spread

Assume a liquid large-cap (e.g. AAPL/MSFT, watchlist §5): `spread_bps = 3`, `slippage_bps = 2`, `COMMISSION_PCT = 0`, `COMMISSION_PER_ORDER = 0`.

```
breakeven_move_pct = 0 + 0 + (3 + 2)/10000 = 0.0005 = 0.05%
```

→ **The price must move 0.05% in your favor just to break even.** For a $200 stock that is **$0.10 per share.** A typical intraday "scalp" target of 0.2–0.5% leaves a thin but real edge — *if* you are right more than half the time. The spread alone, with zero commission, already sets the floor.

#### Worked example B — a per-order commission and a small ticket (the 500€ portfolio)

Now switch on a modest EU-style per-order fee and a small ticket — `COMMISSION_PER_ORDER = €1.00`, `COMMISSION_PCT = 0`, `spread_bps = 3`, `slippage_bps = 2`, ticket `N = €100` (a realistic slice of the 500€ portfolio across a few positions):

```
breakeven_move_pct = 0
                   + 2 × 1.00 / 100        = 0.0200   ( = 2.00%  ← the per-order fee)
                   + (3 + 2)/10000          = 0.0005   ( = 0.05%  spread+slip)
                   = 0.0205 = 2.05%
```

→ **The €100 ticket must move 2.05% intraday just to break even.** That is an *enormous* intraday move to demand from every trade — most intraday moves are far smaller. **The per-order commission alone makes €100 micro-tickets economically dead.** Same fee on a `N = €1,000` ticket: `2 × 1.00/1000 = 0.20%` break-even from commission, total `0.25%` — viable. **Ticket size is the lever.**

#### Worked example C — percentage commission

`COMMISSION_PCT = 0.0005` (5 bps/side), `COMMISSION_PER_ORDER = 0`, `spread_bps = 3`, `slippage_bps = 2`, any `N`:

```
breakeven_move_pct = 2 × 0.0005 + 0 + (3 + 2)/10000
                   = 0.0010 + 0.0005 = 0.0015 = 0.15%
```

→ A percentage commission is **ticket-size-neutral** (good for small portfolios) but stacks directly on the spread: **0.15% break-even.** Acceptable for a scalp targeting 0.3–0.5%, fatal for a scalp targeting 0.1%.

### 1.3 Turnover destroys returns — the multiplier

Cost is paid **per round trip**, so daily cost drag = `breakeven_move_pct × trades_per_day`, and annualized ≈ `× ~252`. A strategy doing **10 round trips/day** at example-A's 0.05% break-even burns **0.5%/day ≈ 126%/yr in costs** before any edge — it must be spectacularly predictive to overcome that. The same strategy at example-C's 0.15% burns **1.5%/day**. This is why **turnover is the enemy** and why §2's `max_trades_per_day` cap is not a nicety but the primary cost-control lever.

| Trades/day | Break-even/trade | Daily cost drag | Annualized cost drag (~252d) |
|---|---|---|---|
| 2 | 0.05% (ex. A) | 0.10% | ~25% |
| 5 | 0.05% | 0.25% | ~63% |
| 10 | 0.05% | 0.50% | ~126% |
| 5 | 0.15% (ex. C) | 0.75% | ~189% |

> The table is deliberately brutal. It shows that **even with zero commission, modest spread, and only 5 trades/day, the strategy starts the year ~63% in the hole.** Microtrading is a *high-bar* activity: the signal edge must be very large and very reliable, or the turnover must be very low. There is no "free" microtrading.

### 1.4 Minimum-edge and minimum-ticket implications

Three rules fall directly out of the math:

1. **Minimum holding edge.** A micro entry signal must have an **expected gross move ≥ `k × breakeven_move_pct`** with a safety multiple `k ≥ ~3` (so the edge survives an adverse spread realization and a sub-50% bad streak). Config: `micro.min_expected_edge_mult: 3.0`. If the entry signal cannot articulate an expected move, it should not fire — "it looks like it'll go up" is not a tradeable edge at this cost level.
2. **Minimum ticket size.** When a per-order commission is in play, set a **floor on notional per micro trade** so the fixed fee stays a small fraction of the move. Reuse the existing `MIN_POSITION_EUR` concept; add `micro.min_ticket_eur` so the per-order fee is capped at, say, ≤10% of break-even. With `COMMISSION_PER_ORDER=€1` and a 0.30% target, the ticket must be **≥ ~€667** for the fee to be <10% of the move — which **immediately tells you the 500€ portfolio cannot run a per-order-fee micro strategy** (see §4).
3. **Prefer percentage commission for small portfolios.** A `COMMISSION_PCT` model is ticket-size-neutral and lets a small budget participate; a per-order model structurally excludes small tickets. This is a config recommendation, not a code change — both are already supported by P10.

---

## SECTION 2 — INTRADAY RISK RULES A SYSTEMATIC MICRO STRATEGY NEEDS

Day-trading without hard risk rails is how accounts die. These rails are **deterministic, cheap, and config-driven** — no new data, no new model, just gates evaluated against state the system already has (`trade_orders`, `portfolio_positions`, `portfolio_nav`). All map onto the **existing `protective_sell` interval-job pattern** and the `BrokerAdapter` seam; none requires a new broker method.

### 2.1 The seven rails

| # | Rail | Config knob (proposed) | What it does | State it reads |
|---|---|---|---|---|
| 1 | **Daily loss limit** | `micro.daily_loss_limit_pct: 0.02` | If today's realized+unrealized micro P&L ≤ −limit × portfolio, **stop all new micro entries for the day** (existing positions still protected by stops). The single most important rail — caps a bad day. | `portfolio_nav` intraday + open micro positions |
| 2 | **Max trades/day** | `micro.max_trades_per_day: 5` | Hard cap on round trips/day per portfolio. The primary **turnover/cost** control (§1.3). Once hit, no new entries. | count of today's micro `trade_orders` |
| 3 | **Max concurrent positions** | `micro.max_open_positions: 3` | Cap simultaneous micro positions (separate from the swing `MAX_OPEN_POSITIONS`). Bounds gross exposure and Pi work per loop. | open micro `portfolio_positions` |
| 4 | **Per-trade risk %** | `micro.per_trade_risk_pct: 0.005` | Position size set so that *distance to the intraday stop* ≈ `risk_pct × portfolio` (ATR-based, reusing `stops.py` maths). Risk-parity sizing, not fixed notional. | ATR(14), portfolio NAV |
| 5 | **Time-stop** | `micro.time_stop_minutes: 45` | If a position hasn't reached its move target within N minutes, **exit flat** — dead capital is opportunity cost and prolonged spread/regime risk. "If the trade was right it would have worked by now." | position `opened_ts` vs now |
| 6 | **Hard intraday stop** | reuse `STOP_ATR_MULTIPLE` / `TRAILING_STOP_PCT` | Per-position trailing/hard stop — **already exists** in `protective_sell`/`stops.py`. Micro just runs it on a tighter multiple and a shorter cadence. | `high_water_mark`, ATR, live VIX |
| 7 | **Forced end-of-day flat** | `micro.eod_flatten_enabled: true`, `micro.eod_flatten_minutes_before_close: 10` | **Liquidate ALL micro positions before the close.** No micro position is ever held overnight — overnight gap risk defeats the entire "same-day" premise. | open micro positions + market calendar |

> **Rail #1 and #7 are non-negotiable.** A daily loss limit prevents one bad session from compounding; the EOD-flatten enforces the definition of "microinversiones **diarias**" — same-day in, same-day out. Everything else tunes turnover and sizing.

### 2.2 How this maps onto the existing seam — two new jobs

The micro sleeve is **two APScheduler jobs that mirror `protective_sell`'s pattern** (interval, market-hours-gated, single-flight, `BrokerAdapter`-only). They are registered as `IntervalTrigger`s in `scheduler/main.py` (like `protective_sell`), **not** in `JOB_SCHEDULE` (which the API shares for next-run times).

**Job A — `micro_entry_loop` (the intraday entry loop).**
- Runs every `micro.entry_interval_min` (default 5) **only during the allowed trading window** (§3, time-of-day gated) and **only when `MICRO_ENABLED=true`**.
- For each active portfolio that opted into a micro version: check rails 1–3 (loss limit not hit, trades-left > 0, slots free); if clear, read the micro entry signals (sibling stream) for the watchlist, size the top candidate by rail #4 (ATR risk-parity), and **`place_order(..., "buy", qty: Decimal, ...)`** through the unchanged seam, tagged `strategy_version='micro-<label>'`.
- Same live-price + `upsert_bars` realism trick `protective_sell` already uses so the simulated fill is sane.

**Job B — `micro_exit_loop` (stops + time-stop + EOD-flatten).**
- Runs every `micro.exit_interval_min` (default 5, ≤ entry interval) during market hours.
- For each open **micro** position: ratchet `high_water_mark`, evaluate the trailing/hard stop (reuse `stops.evaluate_trailing_stop`), evaluate the **time-stop** (rail #5), and — within `eod_flatten_minutes_before_close` of the session close — **force a sell regardless of P&L** (rail #7). All exits via `place_order(..., "sell", ...)`.
- This is `protective_sell` **specialized to micro positions** with two extra exit reasons (time-stop, EOD-flatten). It could even be implemented as an extended mode of `protective_sell` rather than a third job, to save a scheduler registration — a Pi-budget-friendly option (§ budget note).

> **Scoping micro vs swing positions.** Micro and swing positions coexist in the same `portfolio_positions` / `trade_orders` tables. They must be **distinguishable** so the micro exit loop only touches micro positions and EOD-flatten never liquidates a swing hold. Cleanest: tag the originating order's `strategy_version` with a `micro-` prefix and derive position lineage from it (FIFO lot → originating order), or add a nullable `position_kind` discriminator. **This is the one schema/lineage decision the Backend Architect must resolve** — flagged in handoff. No `BrokerAdapter` change either way (`place_order` is unchanged; the tag lives on the order row).

### 2.3 Config block (proposed `config/strategy.yaml`, `micro.*`)

```yaml
micro:
  enabled: false                     # MICRO_ENABLED master switch (also gates scheduler registration)
  entry_interval_min: 5              # micro_entry_loop cadence (market hours only)
  exit_interval_min: 5               # micro_exit_loop cadence (<= entry)
  # --- risk rails ---
  daily_loss_limit_pct: 0.02         # stop new entries when day P&L <= -2% of portfolio
  max_trades_per_day: 5              # turnover/cost cap (the primary lever, §1.3)
  max_open_positions: 3              # concurrent micro positions (separate from swing)
  per_trade_risk_pct: 0.005          # ATR risk-parity: 0.5% of portfolio at the stop
  time_stop_minutes: 45              # exit if target not hit within N minutes
  min_expected_edge_mult: 3.0        # entry edge must be >= 3x break-even (§1.4)
  min_ticket_eur: 500                # floor so a per-order fee stays small (§1.4)
  # --- intraday stop (reuses stops.py; tighter than swing) ---
  stop_atr_multiple: 1.5             # micro is tighter than swing's 2.5
  trailing_stop_pct: 0.03            # fallback when no ATR
  # --- end of day ---
  eod_flatten_enabled: true          # NEVER hold a micro position overnight
  eod_flatten_minutes_before_close: 10
  # --- session gating (see SECTION 3) ---
  session: { ... }                   # defined in §3.4
```

All knobs are **optional with safe defaults** and **version-overlayable** (a `config/strategies/m1.yaml` overlay sets only what it changes), exactly like the existing `trading` section — so the base config leaves everything byte-for-byte unchanged and `enabled:false` means the whole sleeve is inert until deliberately switched on.

---

## SECTION 3 — SESSION & CALENDAR EFFECTS THAT MATTER INTRADAY

The swing stream's calendar effects (`03` §3) are about *days*. Microtrading needs *intraday time-of-day* gating — the U.S. cash session has a well-documented volatility/liquidity smile, and several recurring events make specific minutes either rich (exploitable) or radioactive (avoid). **All gating is pure clock/calendar math — zero data cost, Pi-trivial.** Times below are **U.S. market local (ET)**; the system runs in UTC and already has a market calendar (`calendar.is_market_open_now`), so this is a conversion + window check.

### 3.1 The intraday volatility smile

| Window (ET) | Character | Micro stance |
|---|---|---|
| **09:30–10:00 (open)** | Highest volatility & volume; overnight news/gaps resolve; widest spreads; institutions execute opening orders | **Highest opportunity AND highest cost.** Real moves but wide spreads inflate `breakeven_move_pct`. Trade only with a wider edge requirement; or **avoid the first `open_skip_min`** to dodge the spread spike. |
| **10:00–11:30 (morning trend)** | Trend establishes, spreads normalize, good liquidity | **Best window for systematic micro.** Tightest cost-to-edge ratio. |
| **11:30–13:30 (lunch lull)** | Volume drains, ranges compress, false breakouts, spreads can widen on thin books | **Avoid or down-size.** Low edge, mean-reverting chop; turnover here is pure cost. |
| **13:30–15:00 (afternoon)** | Volume returns, afternoon trend | Acceptable; second-best window. |
| **15:00–16:00 (power hour / close)** | Volume spikes, MOC/LOC imbalance, positioning into close; sharp moves | Opportunity, but **must respect the EOD-flatten** — do not open a position you cannot exit before close. After `eod_flatten` cutoff, **entries off, exits only.** |

> **The cost-of-spread angle (ties to §1):** the open and the lunch lull are exactly when **spreads are widest** — so they inflate `breakeven_move_pct` precisely when the system is most tempted to trade. The morning-trend window is favored not because moves are biggest but because the **move-to-spread ratio** is best.

### 3.2 Event days to avoid or specially handle

| Event | Intraday effect | Micro stance |
|---|---|---|
| **FOMC announcement (2:00 PM ET)** | Violent, whipsaw two-way move on the statement + Powell presser; spreads gap; knee-jerk often reverses (synthesis `03` §3.2) | **Suspend micro entries on FOMC afternoons** (`micro.session.avoid_fomc: true`). The reversal risk + spread blowout defeats a same-day edge. Reuse the existing FOMC date config. |
| **CPI / PPI / NFP release (8:30 AM ET, pre-open or at open)** | Largest scheduled-macro intraday spikes; the open is already volatile, this stacks on it | **Avoid the first `release_skip_min` after such releases** (`micro.session.avoid_macro_release: true`). Macro release dates come from the existing `macro_series` ingestion / FRED calendar. |
| **Triple Witching (3rd Fri Mar/Jun/Sep/Dec)** | Elevated volume + erratic intraday swings, esp. the close (synthesis `03` §3.3) | **Down-size or avoid** (`micro.session.avoid_triple_witching: true`). |
| **Monthly OpEx Friday** | Pinning/gamma noise near strikes | Mild; flag, optionally down-size. Low confidence. |
| **Half-days (day before/after holidays, e.g. early 1:00 PM ET close)** | Thin liquidity, early close, wide spreads | **EOD-flatten cutoff must read the half-day close time** from the market calendar, not assume 4:00 PM. **Critical correctness item** — flattening "10 min before 4 PM" on a 1 PM half-day strands positions for the close. |

> **Half-days are a correctness landmine, not a nicety.** The EOD-flatten (rail #7) **must** derive the actual session close from the market calendar. The existing calendar module knows market hours; the micro loop must query *today's* close time, never a constant.

### 3.3 What to exploit vs avoid — summary

- **Exploit:** the 10:00–11:30 morning-trend window (best move-to-spread ratio), and post-news *directional continuation* **after** the initial spike has resolved (not into it).
- **Avoid:** the first `open_skip_min` (spread spike), the lunch lull (chop = pure cost), the FOMC/CPI/NFP spike windows, and the last minutes before any close except for forced flatten.

### 3.4 Session-gating config

```yaml
micro:
  session:
    timezone: "America/New_York"     # gate in market-local time; system runs UTC
    trade_windows:                   # only enter inside these ET windows
      - { start: "10:00", end: "11:30" }
      - { start: "13:30", end: "15:30" }
    open_skip_min: 30                # skip first N min after open (spread spike)
    avoid_lunch: true                # 11:30-13:30 entries off
    avoid_fomc: true                 # no entries on FOMC afternoons
    avoid_macro_release: true        # skip release_skip_min after CPI/PPI/NFP
    release_skip_min: 30
    avoid_triple_witching: true
    respect_half_day_close: true     # EOD-flatten reads actual session close
```

---

## SECTION 4 — PDT / REAL-WORLD RULES (DOCUMENT FOR PHASE 2)

Phase 1 is paper-only, so none of this binds the simulator — but it **must be documented now** so the Phase-2 real-broker swap doesn't ship an illegal strategy, and so the owner understands why the 500€ micro portfolio is **illustrative, not realistic**.

### 4.1 Pattern Day Trader (PDT) — the 25k rule

- **U.S. rule (FINRA/SEC):** an account in a **margin** account that executes **≥4 day trades within 5 business days** is flagged a **Pattern Day Trader** and must maintain **≥ $25,000 equity**. Below $25k, further day trades are blocked (the account is restricted, typically 90 days). A *day trade* = open **and** close the same security same day — **exactly what microtrading is.**
- **Consequence for our portfolios:** the **`Cartera 500` (500€) portfolio cannot legally run a margin day-trading strategy on a US broker** — it is ~50× below the PDT threshold. With `micro.max_trades_per_day: 5` it would trip PDT on day one. So **the 500€ micro sleeve is purely a simulation illustration** of mechanics and costs; it could never be deployed as-is.
- **Cash-account alternative:** PDT applies to *margin* accounts. A **cash** account can day-trade without the 25k floor **but** is bound by **settlement** (you can only re-trade *settled* funds) — which severely caps round trips per day for a small balance (see §4.2). Either way, small + day-trading + US-equities = structurally constrained.

### 4.2 Settlement (T+1)

- US equities settle **T+1** (one business day, post-2024). In a **cash** account, proceeds from a sale are not "settled cash" until T+1; re-trading unsettled funds repeatedly is a **good-faith / free-riding violation**. This caps a small cash account to roughly **one round trip per settlement cycle per dollar** — directly throttling micro turnover.
- The simulator's `cash_movements` / `compute_cash` model is **instantaneous** (no settlement lag). That's fine for Phase 1 paper trading, but the Phase-2 real adapter would need a settlement-aware available-cash calc. **Flag for the BrokerAdapter Phase-2 work** — not a Phase-1 change.

### 4.3 Portfolio-sizing recommendation

- **Realistic micro portfolio ≥ $25,000** (margin, to clear PDT) — recommend a dedicated `Cartera Micro` seeded at e.g. **30,000€** via `cash_movements`, so the simulation reflects a *legally deployable* day-trading account and its returns/costs are meaningful for a real Phase-2 decision.
- **Keep `Cartera 500` micro runs explicitly labeled "illustrative"** in the dashboard `/info` copy — it demonstrates the cost mechanics (and how brutally per-order fees hit small tickets, §1.2 example B) but is not a deployable account.
- EU/other venues have different rules (no universal PDT, but their own margin/leverage and per-order-fee regimes) — the per-order fee economics of §1 are usually the **binding** constraint for small EU accounts, more than PDT.

---

## SECTION 5 — MICRO-SPECIFIC PERFORMANCE METRICS

The existing performance layer (`performance-metrics.md`) — Sharpe, Sortino, max drawdown, CAGR, Calmar, alpha — is **NAV-based and authoritative** and applies to the micro sleeve unchanged (a micro portfolio still has a NAV series). But NAV-level metrics are **too coarse** for a high-frequency, high-turnover sleeve: they hide whether the edge is real or whether costs are quietly eating it. The metrics below are **trade-level** and **cost-aware**, and they all derive from data the system already writes — primarily `trade_orders` (now including `commission`, P10) via the existing **FIFO `build_round_trips`** matcher, plus `portfolio_nav`.

> **Reuse, don't reinvent.** `win_rate`, `profit_factor`, and `avg_win_loss` **already exist** in `metrics.py` (`performance-metrics.md` §1) and operate on the trips frame. They are *more* central for micro than for swing. The genuinely *new* micro metrics are the cost-drag, expectancy, turnover, hold-time and intraday-drawdown items.

### 5.1 The micro metric set

| Metric | Computation | Source columns / table | Why micro needs it |
|---|---|---|---|
| **Win rate** | `count(pnl>0) / count(trips)` (exists) | trips from `trade_orders` (FIFO) | Baseline — but never read alone. |
| **Profit factor** | `gross_profit / gross_loss` (exists) | trips | The honest "are winners bigger than losers" check; PF<1 = losing gross. |
| **Average win / average loss** | mean winning pnl, mean losing pnl, ratio (exists) | trips | Scalping often has small wins / occasional large losses — this exposes a poor reward:risk. |
| **Per-trade expectancy** | `win_rate × avg_win − (1−win_rate) × |avg_loss|` (per trip, **net of commission**) | trips incl. `commission` | **The single number that says "is each trade worth taking?"** Must be **> 0 after costs**. New function `expectancy(trips)`. |
| **Trades per day** | `count(trips) / distinct_trading_days` | `trade_orders.ts` | Turnover gauge — pairs with §1.3 to estimate cost drag; also verifies the `max_trades_per_day` cap holds. |
| **Average hold time** | `mean(exit_ts − entry_ts)` in minutes | entry/exit `ts` on matched FIFO legs | Confirms it's actually *intraday* (minutes/hours, not days) and that the time-stop bites. |
| **Cost drag** | `Σ commission / |gross P&L|` (and as % of NAV) | `trade_orders.commission`, trips | **The micro-killer metric.** If commissions are 30%+ of gross P&L, churn is eating the edge. With spread modeled (§6), include modeled spread cost too. New function `cost_drag(trips)`. |
| **Max intraday drawdown** | min of `(intraday_NAV / running_max_intraday − 1)` within each session | **intraday** `portfolio_nav` snapshots (see §6 cadence) | Daily-close NAV **cannot see** an intraday −5% dip that recovered by close. A day-trading sleeve must measure peak-to-trough *within* the day — requires sub-daily NAV snapshots. |

### 5.2 Formulas worked (expectancy & cost drag)

**Per-trade expectancy (net):** with win rate 55%, avg win €12, avg loss €9, avg commission €0.40/round-trip:
```
gross_expectancy = 0.55 × 12 − 0.45 × 9 = 6.60 − 4.05 = €2.55 / trade
net_expectancy   = 2.55 − 0.40         = €2.15 / trade   → positive, viable
```
If avg win were €6 instead of €12: `gross = 3.30 − 4.05 = −€0.75`, `net = −€1.15` → **negative even before the spread** → the strategy loses money one trade at a time. Expectancy makes this instantly visible where Sharpe would only show it after months.

**Cost drag:** 120 round trips, gross P&L €900, total commission €48:
```
cost_drag = 48 / 900 = 0.053 = 5.3% of gross P&L
```
Acceptable. At €0.40/trip and a tighter, higher-turnover variant doing 600 trips for the same €900 gross: `240/900 = 27%` — a red flag that turnover is outrunning edge. **Add modeled spread** (§6) and this number jumps further — which is the point.

### 5.3 Where these live

- New pure functions alongside the existing ones in `backend/analysis/performance/metrics.py`: `expectancy(trips)`, `trades_per_day(trips)`, `avg_hold_time(trips)`, `cost_drag(trips)`, `max_intraday_drawdown(intraday_nav)`. Same contract as the existing layer — **DataFrame in, typed result out, no I/O** (`performance-metrics.md` principle).
- `build_round_trips` already produces the trips frame from `trade_orders`; it must **carry `commission` through** so expectancy/cost-drag are net (a small extension — the round-trip shape already isolates entry/exit legs, exactly as `performance-metrics.md` §4 anticipated for "when the seam carries real costs").
- Dashboard: a **dedicated micro panel** (separate from the swing performance cards) showing expectancy, win rate **next to** profit factor (the load-bearing pairing rule from `reporting-structure.md` §4), trades/day, avg hold time, cost drag (amber if >~20%, red if >~40%), and max intraday drawdown. Health palette vs P&L palette rule from `reporting-structure.md` §4 still applies.

### 5.4 Micro-specific thresholds ("what good looks like")

Mirroring `performance-metrics.md` §4's `PerformanceThresholds` (these live in evaluation code, not `strategy.yaml`):

| Field | Suggested value | Meaning |
|---|---|---|
| `micro_expectancy_min` | `> 0` (net of costs) | each trade must be worth taking after commission+spread |
| `micro_profit_factor_min` | `1.3` | tighter is fine; micro lives or dies on PF |
| `micro_cost_drag_warn` / `_bad` | `0.20` / `0.40` | >20% of gross eaten by costs = caution; >40% = churn is the strategy |
| `micro_max_intraday_dd_bad` | `-0.05` | a >5% within-day trough on a *day-trading* sleeve is a risk-rail failure |

---

## SECTION 6 — RISK-CONFIG RECOMMENDATION: m1 vs m2, COST MODEL, NAV CADENCE

### 6.1 The cost model must come first (non-negotiable)

Before **any** micro version is judged, switch on a **realistic cost model** in the backtester and the paper sim, or every micro result is fiction (§1.1, §5):

```yaml
# realistic micro cost assumptions (GLOBAL — every version pays, like P10)
COMMISSION_PCT: 0.0          # keep 0 if modeling a $0-commission broker...
COMMISSION_PER_ORDER: 0.0    # ...but per-order kills small tickets (§1.2-B) — model your real broker
micro:
  cost_model:
    spread_bps: 3            # half-spread×2; liquid large-cap assumption
    slippage_bps: 2          # round-trip slippage
    apply_in_backtest: true  # backtester subtracts spread+slip at fill
    apply_in_paper: true     # PaperBroker marks fill at price ± half-spread
```

> **Flag:** the simulator currently models commission (P10) but **not spread/slippage**. Adding a spread tax at the `PaperBroker`/backtester fill is the **single most important prerequisite** for honest micro evaluation. It stays within the seam (a fill-price adjustment inside `PaperBroker`; `qty` remains `Decimal`; `place_order` signature unchanged) and is GLOBAL like P10 so every version is penalized equally. **This is the "calibrate before shipping" memory rule applied to micro** — and the backtester already exists to do it.

### 6.2 m1 vs m2 — one variable difference (the CLAUDE.md discipline)

Following the project's strict **one-variable-per-experiment** rule (v2→v3→v4 each changed one thing), the first two micro versions are overlays on the base micro config, differing in **exactly one knob**:

- **`m1` (control):** the conservative baseline. Low turnover, wide edge requirement, tight rails.
  ```yaml
  # config/strategies/m1.yaml  (overlay)
  micro:
    enabled: true
    max_trades_per_day: 3
    per_trade_risk_pct: 0.005
    daily_loss_limit_pct: 0.02
    time_stop_minutes: 45
    min_expected_edge_mult: 3.0
  ```
- **`m2` (one change):** **turnover** is the variable under test — does allowing more trades/day help or just add cost drag? **Only `max_trades_per_day` changes.**
  ```yaml
  # config/strategies/m2.yaml  (overlay) — identical to m1 EXCEPT:
  micro:
    enabled: true
    max_trades_per_day: 6      # <-- the ONLY difference vs m1
    per_trade_risk_pct: 0.005
    daily_loss_limit_pct: 0.02
    time_stop_minutes: 45
    min_expected_edge_mult: 3.0
  ```
  m1 vs m2 is then compared by **portfolio performance** (NAV / expectancy / cost drag / max intraday DD) exactly as v1–v6 are compared today (per-portfolio `strategy_label`, the `/compare` route). The hypothesis is explicit and falsifiable: *more turnover earns more net profit only if per-trade expectancy stays positive after the extra cost drag* — and given §1.3, the prior is that **m1 (less turnover) likely wins**, mirroring the existing backtest finding that the simpler control beats the "improvements." Run both through the backtester with the §6.1 cost model **before** going live.

### 6.3 Should micro NAV be snapshotted more frequently than daily?

**Yes — for the micro sleeve specifically.** The existing `update_portfolio_nav` runs once/day (08:15 UTC) and is correct for swing. But a day-trading sleeve that opens and closes within a session is **invisible to a daily snapshot** — the daily NAV may show a flat day while the intraday path swung ±3%. The **max-intraday-drawdown** metric (§5.1) and any honest intraday risk view **require sub-daily NAV points.**

- **Recommendation:** when `MICRO_ENABLED`, have the **`micro_exit_loop`** (which already runs every ~5 min during market hours) **append an intraday NAV snapshot** to a lightweight store on each pass — e.g. rows in `portfolio_nav` tagged intraday, or a separate `portfolio_nav_intraday` table to keep the daily series clean. Config: `micro.nav_snapshot_on_loop: true`.
- **Pi-budget flag (important):** a 5-min snapshot over a 6.5-hour session = **~78 rows/day/portfolio** — trivial in volume, BUT it means the micro loop does extra DB writes and a mark-to-market of micro positions every 5 min. That is well within the Pi budget **as long as it is gated to `MICRO_ENABLED` and to market hours**, and **as long as it only marks the (few) micro positions**, not the whole swing book each pass. **Do not** snapshot the full multi-portfolio book every 5 minutes — that would risk the scheduler's ~400 MB peak budget. Keep the intraday loop lean: micro positions only, market hours only, off by default.

### 6.4 Pi-budget & simulation-constraint conflicts (consolidated flags)

| Item | Conflict | Resolution |
|---|---|---|
| Two new interval jobs (entry + exit) every 5 min | More frequent wake-ups than the daily pipeline; live-price fetches (Yahoo 429s already noted in `protective-sell.md`) | Gate hard to `MICRO_ENABLED` + market hours; reuse `protective_sell`'s hardened `fetch_live_prices` with stored-close fallback; **consider folding micro-exit INTO `protective_sell`** to save a registration. |
| Intraday NAV snapshots | Extra DB writes/marks each loop | Micro positions only, market hours only, off by default (§6.3). Volume is trivial; the *frequency of marks* is the watch item, not row count. |
| Live intraday prices | Same Yahoo rate-limit caveat as `protective_sell` (`protective-sell.md` reliability note) | Inherit the existing fallback-to-stored-close; a true real-time micro strategy would need a dedicated quote provider — **Phase 2**, flagged. |
| Spread/slippage model | Not yet in `PaperBroker` | Add as a fill adjustment inside the seam (§6.1) — required for honest evaluation, GLOBAL like P10. |
| 500€ micro portfolio | PDT-illegal + per-order-fee-dead (§1.2-B, §4) | Keep as **illustrative only**; recommend a ≥30k€ `Cartera Micro` for any deployable read. |
| Same-day premise | Overnight gaps defeat it | **EOD-flatten (rail #7) is mandatory** and must read the real (possibly half-day) close. |

---

## Handoff notes

**What this document produced:** the transaction-cost economics of microtrading with the break-even formula worked through three commission/spread scenarios (the verdict: **microtrading is never free — spread+slippage set a ~0.05–0.15% per-trade floor, and turnover multiplies it into double-digit annual cost drag**); the seven intraday risk rails and how the **entry loop + exit/EOD-flatten loop** map onto the existing `protective_sell` interval-job + `BrokerAdapter` seam (no new broker method); intraday session/calendar gating (open spread-spike, lunch lull, power hour, FOMC/CPI/NFP/Triple-Witching avoidance, half-day close correctness); PDT/settlement reality (the 500€ portfolio is illustrative, recommend ≥$25k); the micro performance-metric set (expectancy, cost drag, trades/day, hold time, max intraday drawdown) all derived from existing `trade_orders.commission` + FIFO trips + intraday NAV; and the **m1 vs m2 one-variable** config recommendation with a mandatory realistic cost model and intraday NAV snapshots.

**Must-have rules (the ones that are non-negotiable):**
1. **Model spread+slippage before judging any micro version** — the default frictionless sim lies (§6.1).
2. **Daily loss limit** (rail #1) and **forced EOD-flatten** (rail #7, reading the real/half-day close) — these define and protect "same-day."
3. **Hard `max_trades_per_day` cap** — the primary cost/turnover lever (§1.3).
4. **`min_ticket_eur` / prefer `COMMISSION_PCT` for small portfolios** — per-order fees kill small tickets (§1.2-B).
5. **Everything via `BrokerAdapter` `place_order`, `qty: Decimal`, nothing hardcoded, all `micro.*` config, version-overlayable, off by default.**

**For the Backend Architect (the one decision to resolve):** how micro positions are **distinguished** from swing positions in the shared `portfolio_positions`/`trade_orders` tables so the micro exit loop and EOD-flatten only touch micro positions (proposal: `strategy_version='micro-<label>'` prefix → FIFO lot lineage, or a nullable `position_kind` discriminator). No `BrokerAdapter` change either way.

**For the AI Engineer / Experiment Tracker:** new pure metric functions (`expectancy`, `trades_per_day`, `avg_hold_time`, `cost_drag`, `max_intraday_drawdown`) extend `metrics.py`; `build_round_trips` must carry `commission` through to net them. m1 vs m2 compared on the existing per-portfolio `strategy_label` / `/compare` machinery.

**Out of scope here (sibling stream / Phase 2):** the micro *entry signals* themselves (intraday momentum/breakout/mean-reversion — a separate research stream), a dedicated real-time quote provider, settlement-aware available-cash for the Phase-2 real adapter, and intraday options/gamma data. **Microtrading ships disabled (`MICRO_ENABLED=false`) and behind a realistic cost model — calibrate in the backtester before going live, per the project's standing rule.**
