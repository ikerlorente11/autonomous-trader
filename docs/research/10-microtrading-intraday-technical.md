<!-- Agent: Investment Researcher | Phase: 0-micro | Depends on: docs/research/00-signal-synthesis.md -->

# Phase 0-micro — Intraday Technical Signals, Microstructure & Universe (Day-Trading Stream)

**Stream:** Intraday price signals + market microstructure + day-trading universe selection.
**Goal:** Identify which **same-day** (open→close, hold ≈ minutes to a few hours) strategies have a
*real, documented* systematic edge, define them concretely (entry / exit / stop / horizon /
hit-rate), pick the day-tradeable universe, and map them onto **this** codebase's
`Indicator` / `score_universe` pattern so the micro sleeve is buildable the same way the daily
sleeve was — every threshold in `config/strategy.yaml`, the `BrokerAdapter` seam untouched.

> **Scope guardrail (inherited from CLAUDE.md + 00-signal-synthesis.md).** This is a *paper* system
> on a **Raspberry Pi 4 / 4 GB**. Three hard filters apply to everything below, and to one more than
> the daily stream had: **(1)** computable from **free / free-tier intraday** data; **(2)** cheap on
> ARM64/4 GB *at intraday cadence* (the binding new constraint — minute bars are 60–390× the row
> volume of daily); **(3)** backed by published microstructure / day-trading evidence, not
> trading-room folklore. Where an idea is **not feasible intraday on this hardware/data**, it is
> flagged ⛔ explicitly rather than quietly dropped.

> **Relationship to the daily system.** The daily sleeve predicts **1–4 weeks** ahead and *holds
> across days*. The micro sleeve predicts **the rest of today** (minutes–hours) and **is flat by the
> close**. They are different horizons, different data, different universes, and **must not share a
> composite score** — a 12-1 momentum percentile says nothing about the next 30 minutes. They share
> only: the `Indicator` base contract, the `score_universe` shape, the `PaperBroker` seam, the
> multi-portfolio model (`kind='micro'`), and the strategy-overlay discipline (`m1.yaml`, `m2.yaml`).

---

## SECTION 0 — The honest premise (read before the strategies)

Intraday day trading is the **hardest** place to find systematic edge, and the literature is blunt
about it. Three findings frame every recommendation that follows:

1. **The base rate is brutal.** Barber, Lee, Liu & Odean's studies of Taiwanese day traders (the
   cleanest full-population dataset that exists) found **~80% of day traders lose money** net of
   costs, and only **~1%** are reliably profitable year over year. The losers' problem is almost
   never signal — it is **cost drag and overtrading**. This is the single most important fact for a
   *micro*-ticket system: **costs, not alpha, are the first-order term** (Section 3).
2. **Intraday edges are smaller and decay faster than daily anomalies.** A daily momentum premium of
   ~1%/month survives decades; intraday patterns (ORB, the open-auction imbalance) have **thinner
   margins** and are more crowded by HFT. We are not competing with HFT on latency — a Pi fetching
   delayed/EOD-grade intraday bars **cannot** scalp. Our realistic playing field is the **slower
   intraday structural patterns** (opening range, VWAP, relative-volume regime, EOD drift) that play
   out over **15 minutes to a few hours**, not the sub-second tape.
3. **What *does* have published support:** opening-range / first-hour patterns, VWAP as an
   institutional reference price, relative-volume ("RVOL") as a same-day attention/liquidity proxy,
   and the **end-of-day momentum** effect (Heston, Korajczyk & Sadka 2010: returns in the **last
   half-hour** are predictable from the **first half-hour** and from the same period on prior days).
   These are the spine of Section 1.

> **Bottom line up front:** a paper micro sleeve on a Pi is a legitimate *research* exercise and a
> good fit for the project's experiment discipline, but the realistic expectation is **edge that
> barely clears costs even in paper**, and **negative net edge the moment a real spread+commission is
> charged** on tiny tickets. The recommended first version (`m1`, Section 5) is deliberately the
> *most cost-robust, lowest-frequency* intraday pattern, not the most exciting one.

---

## SECTION 1 — Intraday strategies with documented edge

Convention: **Horizon** = typical hold. **Frequency** = setups/day/symbol. **Realistic hit-rate** =
win rate *before* costs at a sane reward:risk (R:R), from the day-trading literature and practitioner
backtests — treated as a *prior*, to be re-measured by our backtester, never as a promise. All
timeframes assume 1m bars aggregated to 5m/15m (see Section 4 — we do **not** trade off 1m noise).

Ranking is by **cost-robustness × evidence × feasibility on this stack**, not by glamour.

| # | Strategy | Horizon | Freq/sym/day | R:R target | Realistic hit-rate (pre-cost) | Evidence | Pi/data feasible? |
|---|---|---|---|---|---|---|---|
| 1 | **VWAP trend/reversion** | 30 min–3 h | 1–3 | 1.2–1.8 : 1 | 45–55% | ★★ (institutional benchmark) | ✅ |
| 2 | **Opening-Range Breakout (ORB)** | 30 min–2 h | 0–1 | 1.5–2.5 : 1 | 35–45% | ★★ (first-hour info) | ✅ |
| 3 | **Relative-volume momentum** (RVOL gate, not standalone) | 30 min–2 h | 0–2 | filter, not entry | n/a (raises others' hit-rate ~5–10pp) | ★★ | ✅ |
| 4 | **End-of-day (last-30-min) momentum** | 15–40 min | 0–1 | 1.2–1.5 : 1 | 50–55% | ★★★ (Heston et al. 2010) | ✅ |
| 5 | **Intraday mean-reversion** (5m/15m RSI/Bollinger) | 15–60 min | 1–4 | 1 : 1–1.3 | 52–58% (low R:R) | ★ regime-dep. | ⚠️ |
| 6 | **Gap-and-go** (overnight-gap continuation) | 30 min–2 h | 0–1 (gap days only) | 1.5–2 : 1 | 40–50% | ★ (event-dep.) | ⚠️ (needs gap+news) |

### 1.1 VWAP trend / reversion — **the spine of the micro sleeve**

- **What it is.** VWAP = Σ(price×volume)/Σvolume, **reset at the session open** and accumulated
  through the day (an *intraday-anchored* VWAP, not a rolling window). It is the single most-watched
  intraday reference because large institutional orders are benchmarked to it (VWAP execution algos),
  so price genuinely *gravitates to and reacts at* VWAP.
- **Two regimes, one indicator (mirrors the daily momentum-vs-reversion split):**
  - **VWAP trend (continuation):** price holds **above** VWAP with a rising VWAP slope → bias long;
    enter on a pullback *to* VWAP that holds (close back above within 1–2 bars). Works on
    high-RVOL trending days.
  - **VWAP reversion (fade):** price stretches **far from** VWAP (e.g. > 1.5–2× the day's average
    bar range, or > k × intraday-ATR) on *low/declining* RVOL → fade back toward VWAP. Works on
    range/chop days.
- **Entry/exit/stop (concrete defaults — all config):**
  - Entry: 5m close re-crosses VWAP in the trade direction **and** RVOL ≥ `rvol_min` (Section 1.3).
  - Stop: opposite side of VWAP by `vwap_stop_atr × ATR_intraday(14)` (fallback `vwap_stop_pct`).
  - Target: trend → trail under each new 5m higher-low / VWAP; reversion → **VWAP itself** is the
    target (take profit when price tags VWAP).
  - **Hard time stop:** flat by `eod_flat_time` (e.g. 15:55 ET) regardless — this is a same-day sleeve.
- **Expected hold:** 30 min–3 h. **Why it works:** VWAP is a real coordination point for institutional
  flow; the reversion leg harvests the over-extension of uninformed momentum, the trend leg rides
  confirmed institutional accumulation. **Realistic hit-rate 45–55%** with R:R ≥ 1.3 → positive
  expectancy *before* costs.

### 1.2 Opening-Range Breakout (ORB)

- **What it is.** Define the **opening range** = high/low of the first `or_minutes` (15 or 30 min) of
  the regular session. Go **long on a 5m close above the OR high**, **short below the OR low**
  (paper allows shorts; real-world short-locate caveat in §3.5).
- **Why it works.** The first 15–30 min concentrates overnight-news price discovery and the heaviest
  volume of the day; a clean break of that range marks the side that won the auction. First-hour
  information content is well documented; the **opening 30-min return predicts the rest-of-day return**
  (a corollary of Heston et al.).
- **Entry/exit/stop:**
  - Entry: 5m close beyond OR boundary, **confirmed by RVOL ≥ `rvol_min`** (an unconfirmed break is
    the classic false-breakout trap — the RVOL gate is what separates ORB-that-works from
    ORB-that-doesn't).
  - Stop: the **opposite** OR boundary (or `or_stop_atr × ATR_intraday`), whichever is tighter.
  - Target: `or_range_mult × (OR_high − OR_low)` projected from the breakout (1.5–2.5×), or trail.
  - Flat by `eod_flat_time`.
- **Horizon:** 30 min–2 h. **Setups:** ≤1/symbol/day (the OR breaks once). **Hit-rate 35–45%** — low,
  but R:R 1.5–2.5 keeps expectancy positive; ORB is a **low-win-rate, high-R:R** pattern, the opposite
  profile of reversion. This profile difference is exactly why `m1` vs `m2` should contrast them
  (Section 5).

### 1.3 Relative-volume (RVOL) momentum — a **filter**, not a standalone entry

- **What it is.** RVOL = today's cumulative volume *up to this time of day* ÷ the average cumulative
  volume *at the same time of day* over the trailing `rvol_lookback` sessions (e.g. 20). RVOL = 2.0
  means "twice the usual participation by now." It is the cleanest same-day proxy for *attention,
  liquidity, and the probability a move follows through*.
- **Why it's a filter:** every intraday breakout/trend strategy's hit-rate is **conditional on
  participation**. A break on RVOL 0.7 is noise; the same break on RVOL 2.5 has real flow behind it.
  Published and practitioner evidence both show RVOL gating lifts breakout follow-through materially
  (≈+5–10pp hit-rate in our prior). It is **not** an entry trigger on its own (high volume ≠ direction).
- **Use:** a multiplicative **gate** on ORB / VWAP-trend entries (`rvol_min` ≈ 1.5–2.0), and as the
  morning **universe ranker** (Section 2): rank tradeable names by RVOL to spend the day's attention
  on the names actually *in play*.

### 1.4 End-of-day (last-30-min) momentum — **highest-evidence intraday signal**

- **What it is.** Heston, Korajczyk & Sadka (2010) document that the **last-half-hour return is
  positively predicted by the first-half-hour return** of the same day (and by the same half-hour on
  prior days — intraday periodicity). Practically: names that were strong in the **opening 30 min**
  tend to be strong again into the **close**.
- **Entry/exit/stop:**
  - Signal computed once, late session (e.g. `eod_entry_time` 15:25 ET): `r_open30` = return over the
    first 30 min; rank the universe by `r_open30 × sign`, gate by RVOL.
  - Enter top names in the direction of `r_open30`; **target = the close** (this is the rare strategy
    whose exit is a *clock*, not a price).
  - Stop: tight `eod_stop_atr × ATR_intraday`; flat at `eod_flat_time` no matter what.
- **Horizon:** 15–40 min — the shortest, but also the **most evidence-backed and the most
  cost-robust per unit time** because the exit is deterministic. **Hit-rate 50–55%**, low R:R.
- **Feasibility:** needs only the first-30-min return (computable from 5m bars) and a late-session
  trigger — trivially cheap. **Strong candidate for an early micro version.**

### 1.5 Intraday mean-reversion (5m/15m RSI / Bollinger) ⚠️

- **What it is.** On **range days**, fade short-term extremes: 5m/15m **RSI(2) or RSI(14)** crossing
  back from oversold/overbought, or a tag of the **lower/upper Bollinger band** (20-period, 2σ on 5m).
- **Why it works (and when it doesn't).** Same behavioral basis as the daily reversion profile —
  short-horizon overreaction reverts. **But intraday it is regime-fragile:** in a trending/high-RVOL
  session, "oversold" keeps getting more oversold and the strategy bleeds. It **must** be gated by an
  intraday regime read (price *inside* the day's range, RVOL not elevated, VWAP slope flat). High
  win-rate (52–58%) but **low R:R (~1:1)** → expectancy is thin and **costs eat it fastest** of any
  strategy here. ⚠️ Flagged: ship only *after* the cost model proves the others clear their spread.

### 1.6 Gap-and-go ⚠️

- **What it is.** On a meaningful **overnight gap** (open vs prior close > `gap_min_pct`, typically on
  news/earnings), trade **continuation** of the gap direction if the first 5–15 min holds above (gap
  up) the opening level.
- **Why it's deferred.** It is **event-driven** (needs a gap detector *and*, to be safe, a news
  catalyst — naked gaps fade as often as they go), occurs only on gap days, and overlaps the
  daily sleeve's PEAD/news machinery. ⚠️ Defer to a later micro version; the gap *detector* (open vs
  prior `market_bars` close) is cheap and can ship as an **observation-mode** signal first.

### 1.7 ⛔ Explicitly NOT feasible intraday on this stack

- **Sub-minute scalping / tape reading / order-book imbalance** — needs L2/tick data and
  co-located latency. We have neither; a Pi on delayed bars would be picked off. ⛔
- **True real-time VWAP execution / passive limit-at-VWAP fills** — the *signal* VWAP is fine; modeling
  realistic *passive* fills is not, in paper. We assume **marketable** fills with explicit slippage. ⛔
- **Options/0DTE intraday, futures, FX micro** — out of universe (equities/ETFs only, Phase 1). ⛔
- **Anything requiring continuous (every-few-seconds) polling** — the free intraday APIs' rate limits
  and the Pi's budget cap us at a **bar-close cadence of ≥5 min** (Section 4). ⛔

---

## SECTION 2 — The micro universe: what is day-tradeable, and how to rank it each morning

Day-trading edge lives **only** in names that are liquid enough that the spread doesn't eat the move
and volatile enough that there *is* a move. The daily sleeve's 62-symbol watchlist is the wrong
universe twice over: it includes low-ATR defensives (XLU, PG, KO — no intraday amplitude) and
rate-proxy/illiquid-intraday names, and it's larger than a Pi can poll intraday.

### 2.1 What makes a name micro-tradeable (static eligibility filter)

| Criterion | Threshold (config default) | Why |
|---|---|---|
| **Dollar volume** (avg daily $ traded) | ≥ **$50M/day** (prefer ≥ $200M) | Spread + market impact scale inversely with $-volume. Below this, micro tickets still move the tape. |
| **Bid/ask spread** | ≤ **5 bps** (≤ $0.02 on a $50 stock) | The spread is paid **twice** per round trip; it is the dominant cost (Section 3). Hard gate. |
| **Intraday ATR%** | **1.5%–5%** of price | < 1.5% → no amplitude to clear costs; > 5% → gap/headline risk, slippage blows out. The daily stream's 1.5–4% sweet spot, widened slightly at the top for intraday. |
| **Price range** | **$10–$600** | < $10: spread-as-% explodes, low-float pump risk. > $600: fractional-share rounding noise on tiny tickets (mitigated by fractional support, but still). |
| **Float / not low-float** | exclude **low-float (<20M sh)** & recent IPOs | Low-float runners are un-modelable (halts, 20% gaps); they violate the clean-fill assumption. |
| **Listing/type** | NYSE/Nasdaq common stock + liquid ETFs only | No OTC, no leveraged/inverse ETFs (decay), no halts-prone microcaps. |

These are **static** (recomputed weekly from daily `market_bars` we already store — no new fetch).

### 2.2 The morning ranker (dynamic, intraday)

Eligibility (2.1) defines the **pool**; the **morning ranker** picks the day's working set from it:

1. **Pre-open / early-session RVOL** (Section 1.3) — the dominant input; "what's in play today."
2. **Overnight gap %** (open vs prior close) — gappers concentrate intraday opportunity.
3. **Intraday-ATR% percentile** — favour the live-volatility names within the pool.
4. **News/catalyst tag** (optional, reuses the daily sleeve's `news_sentiment` table) — a tiebreaker.

Rank the pool by a weighted blend of these (rank-normalized, exactly like `score_universe` does for
the daily sleeve) and take the **top `micro_universe_size`** for the day.

### 2.3 Should micro use a tighter subset of the 62-symbol watchlist? — **Yes, much tighter.**

- **Recommendation:** a **dedicated micro pool of ~12–20 symbols**, a *strict subset* of the existing
  watchlist that passes 2.1, **plus the index ETFs as the always-on liquid core**. Concretely, the
  high-$-volume, mid-high-ATR names already in the list: **SPY, QQQ, IWM** (ETF core — tightest
  spreads on earth), and liquid high-beta singles **NVDA, AMD, TSLA, AAPL, MSFT, META, AMZN, AVGO,
  GOOGL, NFLX, LLY**. Exclude every low-ATR defensive/utility/staple and every rate-proxy/REIT.
- **Why tighter, not the same list:** (a) intraday polling cost is linear in universe size and the Pi
  caps us (Section 4); (b) half the daily watchlist has no intraday amplitude or has bad intraday
  spreads; (c) day-trading edge is **concentrated** in the few names "in play" — breadth *hurts* here,
  the opposite of the diversification logic that governs the multi-week sleeve.
- **Stays runtime data, never hardcoded.** This subset is materialized into a **`micro_watchlist`**
  (or a `kind`/`tradeable_intraday` flag on the existing `watchlist`) **at runtime**, seeded from a
  committed `config/micro_watchlist.seed.csv` exactly like the daily seed — editable via API, the API
  remains source of truth (CLAUDE.md default-watchlist-seed pattern).

---

## SECTION 3 — Position sizing & costs at micro scale (the part that actually decides P&L)

This is the **first-order** section. At micro-ticket size, **costs dominate alpha**; a strategy with a
real 0.3% edge per trade is *net negative* if the round-trip cost is 0.4%. Get this wrong and no signal
quality can rescue the sleeve — exactly the lesson the daily diagnostics learned the expensive way
(`01-diagnostico-perdidas.md`: no commission model → whipsaw looked free; it isn't).

### 3.1 The cost stack per round trip

| Cost | Size on a liquid name | Notes |
|---|---|---|
| **Bid/ask spread (½ each side, ×2)** | **2–10 bps** round trip | The **dominant** cost. SPY ≈ 1 bp; NVDA/AMD 2–5 bps; thinner names 10 bps+. Paid on *every* round trip — and micro trades MANY. |
| **Slippage (marketable fill)** | 1–5 bps/side | We assume marketable fills (no passive VWAP fills in paper). Model with the project's existing `SLIPPAGE_PCT` per side. |
| **Commission** | $0 retail US / `COMMISSION_*` | The project already has `COMMISSION_PCT × notional + COMMISSION_PER_ORDER` (P10). **Must be ON for the micro A/B** — a commission-free backtest of a high-frequency strategy is a *fantasy* (Reality Checker would reject it). |
| **Borrow/short fee** | n/a (paper) | Only if shorting; document, don't model in Phase 1. |

### 3.2 Minimum edge to overcome costs (the gate every micro strategy must clear)

> **Required gross edge per trade ≥ (2 × half-spread) + (2 × slippage) + (commission as %) + a margin.**

Worked example, liquid name, realistic costs: spread 4 bps round trip + slippage 4 bps round trip +
commission 0 = **8 bps (0.08%) just to break even**. A strategy targeting a **0.3% average gross move**
keeps **~0.22%** net — *if* the hit-rate × R:R expectancy is positive. A strategy targeting a **0.1%**
move (typical scalp) is **net negative** before it even considers being wrong half the time. **This is
the math that kills most intraday systems and is why the recommended `m1` targets larger, lower-
frequency moves (ORB/VWAP, ≥0.3% targets), not scalps.**

**Implication for design:** the micro action gate must enforce a **minimum-target filter** — only take
a setup whose projected target (ATR-based) is ≥ `min_edge_mult × round_trip_cost`. This is the
micro-sleeve analogue of the daily `min_score_to_act`, and it is **cost-aware**, which the daily gate
is not.

### 3.3 Fractional shares — essential at €500, irrelevant at €100k

The project already supports fractional shares (`ALLOW_FRACTIONAL`, `qty: Decimal` in the seam). For
micro this is **mandatory on the small portfolio**: a €500 book taking a position in NVDA (~$900) can
only participate fractionally. Fractional rounding noise is negligible at these prices and the seam
already honours `Decimal` qty — **no seam change**.

### 3.4 How many concurrent micro positions?

| Portfolio | Net capital | Recommended concurrent micro positions | Per-position size | Rationale |
|---|---|---|---|---|
| **micro-500** | €500 | **1–2** | 25–50% of book (fractional) | Below ~3 names, diversification is moot; the binding constraint is **per-trade cost as % of a tiny ticket**. Concentrate to keep each ticket large enough that fixed costs don't dominate. Keep a cash reserve (`MIN_CASH_PCT`). |
| **micro-100k** | €100k | **3–6** | 8–15% of book | Enough to spread across the day's top-RVOL names without any single ticket moving the tape. More than ~6 intraday names exceeds what a Pi can *manage* (poll + stop-check) every 5 min and dilutes attention. |

> **Asymmetry to expect (and measure):** the **same strategy will look better on micro-100k than on
> micro-500**, purely because fixed/percentage costs are a smaller fraction of larger tickets and it
> can diversify across setups. The €500 micro book is the **honest stress test** — if an intraday
> strategy is net-positive there *after* costs, it's real. This mirrors the daily diagnostics finding
> that cost drag scales ~199× between the two books but bites the small one hardest in % terms.

### 3.5 Real-world rules to document (paper ignores them; Phase 2 cannot)

- **Pattern Day Trader (PDT) rule (US):** an account < **$25,000** is limited to **3 day trades per
  rolling 5 business days**. A €500 (≈ $540) micro book would be **PDT-blocked from day trading at
  all** at a US broker. **Paper has no such block**, so the sim can day-trade the small book freely —
  but the report **must flag** that micro-500 is *not transferable to a real US retail account* without
  ≥$25k or a non-US/PDT-exempt venue. This is a headline caveat, not a footnote.
- **Short-sale locate / uptick (SSR):** intraday shorts need a borrow and are subject to SSR after a
  −10% day. Paper can short freely; document that the short legs of ORB/VWAP are **less transferable**
  than the long legs.
- **Settlement (T+1) / good-faith violations:** rapid in-and-out on unsettled cash can trip
  good-faith violations in a cash account. Irrelevant in paper, real in Phase 2.

---

## SECTION 4 — Data & indicator mapping onto THIS codebase

### 4.1 Intraday data — the binding feasibility constraint

The chosen plan is a **chain of free/free-tier providers** behind the existing `MarketDataProvider`
Protocol seam (no analysis code changes to swap them):

| Provider | Intraday coverage | Limit / caveat | Role |
|---|---|---|---|
| **yfinance intraday** | 1m ≈ last **7 days**; 5m/15m ≈ last **60 days** | Delayed, rate-limited, frames go empty under load; **history window is tiny** (can't backtest 1m beyond a week) | **Primary** for live 5m/15m bars; **backtest reach is the limiting factor** |
| **Finnhub** (free) | candle endpoint, 60 calls/min | Free intraday increasingly gated; resolution/history vary | **Fallback** + the existing news tie-in |
| **Twelve Data** (free) | intraday, 8 calls/min, 800/day | Tight daily cap | **Second fallback**; budget calls carefully |

> ⛔ **Feasibility flags (must be in the implementation plan):**
> - **1m history is ~7 days** — a 1m backtest **cannot** span the months the daily backtester does.
>   **Recommendation: trade and backtest on 5m/15m bars** (≈60-day reach), not 1m. The strategies in
>   Section 1 are *designed* for 5m/15m precisely so this constraint doesn't bind.
> - **Polling cadence ≥ 5 min.** With ~12–20 symbols and 3 chained providers under free rate limits on
>   a Pi, a **5-minute bar-close poll** is the realistic floor. No sub-minute, no per-second polling. ⛔
> - **No clean point-in-time intraday history for long backtests** → the micro backtester is
>   **shallow (weeks, 5m)**, not deep (years, daily). The Experiment Tracker must size significance
>   expectations accordingly: micro verdicts need **many trading days of forward paper**, not a long
>   historical backtest, because the history simply isn't retrievable for free.

### 4.2 Storage — a NEW table, do not overload `market_bars`

`market_bars` PK is **`(symbol, ts)` with no interval column** (confirmed: `backend/db/models.py:31`)
— it is daily-only by construction. Mixing 5m bars in would corrupt every daily query and the
continuous aggregates.

> **Recommendation:** new hypertable **`intraday_bars`** with PK **`(symbol, ts, interval)`** (interval
> ∈ {`1m`,`5m`,`15m`}), same OHLCV columns, **aggressive TimescaleDB compression + a short retention
> policy** (e.g. keep 5m for 90 days, 1m for 14 days — beyond the free fetch window there's no point).
> Volume estimate: 16 symbols × 78 5m-bars/session × 252 ≈ **315k rows/yr** for 5m — fine compressed,
> but **this is the one place the micro sleeve materially grows the DB**, so retention must be set or
> it will outgrow the Pi. Flag for Database Optimizer.

### 4.3 Indicator mapping — what ports, what's new

The micro sleeve reuses the **exact `Indicator` base contract** (`backend/analysis/indicators/base.py`:
`compute(df) -> Series`, `latest_score(df) -> 0–100`, all-NaN on insufficient data, params from config)
and the **`score_universe` pass** (one universe pass, optional rank-normalization, action gate). It just
runs on `intraday_bars` and a micro-specific config. **The `BrokerAdapter`/`PaperBroker` seam is
untouched** — micro portfolios are `kind='micro'`, `portfolio_id` stays a `PaperBroker` constructor arg,
`place_order` is unchanged, `qty` stays `Decimal`.

**Ports as-is (run on 5m/15m bars instead of daily — same class, different config):**
- **`RelativeStrengthIndex`** (`momentum.py`) → 5m/15m RSI, `mode: mean_reversion` for the §1.5
  fade. **Already supports the inverted (oversold-high) sub-score.** Zero new code.
- **`AverageTrueRangeIndicator`** (`volatility.py`) → **intraday ATR** for stops/sizing and the
  amplitude filter. Zero new code — just feed it 5m bars; the sub-score logistic still applies.
- **`PriceMomentum`** (`momentum.py`) → reused for **§1.4 EOD momentum** as a short-lookback intraday
  momentum (`period`/`skip` in *bars* = the first-30-min window). Same class, micro config.

**New indicators needed (each a thin `Indicator` subclass, params in config):**

| New indicator | `signal_id` | `compute` sketch | latest_score |
|---|---|---|---|
| **AnchoredVWAP** | `vwap` | session-anchored Σ(typical_price×vol)/Σvol from the day's open; emit **(close − VWAP)/ATR** as the signed stretch | logistic of the signed ATR-normalized distance (trend: above→high; reversion mode: inverted, like RSI) |
| **OpeningRange** | `orb` | first `or_minutes` high/low; emit signed breakout distance beyond the range in ATR units (0 inside the range) | logistic of breakout distance; **gated to 0 until RVOL ≥ min** |
| **RelativeVolume** | `rvol` | cumulative vol-to-now ÷ avg cumulative-vol-at-this-time over `rvol_lookback` sessions | logistic centred at RVOL=1; **used as a multiplicative gate, not a weighted score** |
| **GapPercent** (deferred/obs) | `gap` | session-open ÷ prior-`market_bars`-close − 1 | logistic; ships **observation-mode** first (no weight), like momentum did in v4 |

> **Design note — RVOL is a *gate*, not a weight.** Unlike daily signals which all sum into a weighted
> composite, RVOL must **multiply/threshold** the ORB and VWAP-trend entries (high volume confirms
> direction, it doesn't *provide* direction). The cleanest fit to the existing engine is to keep RVOL
> as an `Indicator` (so it's computed/persisted in observation mode uniformly) **but consume it in a
> micro-specific action gate** in the scorer/ranker, not as a `scoring.weights` entry — analogous to
> how the daily `market_filter` is an absolute gate layered above the per-symbol score, not a weight.

### 4.4 The micro action gate (cost-aware, intraday)

The daily gate is `score ≥ min_score_to_act` + the market-uptrend filter. The micro gate adds three
intraday-specific, **all-config** conditions, layered the same way the daily `market_filter` is layered
above the per-symbol score in `score_universe`:

1. **RVOL gate:** `rvol ≥ rvol_min` (no entry on dead volume).
2. **Cost gate:** projected ATR target ≥ `min_edge_mult × round_trip_cost` (§3.2) — refuse trades that
   can't clear their own spread.
3. **Time gate:** no new entries after `last_entry_time`; **force-flat all positions at `eod_flat_time`**
   (the protective-sell job's micro analogue, but a hard clock, not just a trailing stop).

### 4.5 Scheduler — a new interval job, not the daily sequence

The 7-job daily sequence is **EOD-batch** and does not fit intraday. The micro sleeve needs:
- A **market-hours interval job** `run_micro` every `micro_interval_min` (≥5 min), gated by
  `MICRO_ENABLED` and market hours — **exactly the registration pattern of the existing
  `protective_sell` `IntervalTrigger`** (`scheduler/main.py`, not in `JOB_SCHEDULE`). It: fetches the
  latest 5m bars for the micro pool → `score_universe` on `intraday_bars` with the micro config →
  applies the §4.4 gate → trades each `kind='micro'` portfolio under its own overlay.
- A **morning `rank_micro_universe`** job (just after the open) to pick the day's working set (§2.2).
- The **EOD force-flat** at `eod_flat_time` (can be the same interval job detecting the clock, or a
  dedicated one-shot) — non-negotiable: the micro sleeve **never holds overnight**.

All idempotent (re-running a 5m slot must not double-fill — same natural-key discipline as the daily
jobs). RAM: intraday compute is the same pandas math on small frames; **the cost is the extra fetches
and the `intraday_bars` table**, which is why universe size and retention are capped (§4.1–4.2).

---

## SECTION 5 — Recommended first micro version `m1` and contrast `m2`

Following the project's **one-variable-per-version** discipline (`04-plan-v4.md`: "una variable por
experimento") and its bias toward the **most cost-robust** option first.

### `m1` — the control: **EOD momentum + VWAP-trend, cost-gated, RVOL-confirmed**

**Why this as the first version:** it is the **most evidence-backed (Heston et al. ★★★) and most
cost-robust** combination — deterministic clock-based exit for the EOD leg, larger ATR-based targets
for the VWAP-trend leg, both gated by RVOL and the cost filter so they **only fire when the move can
clear its spread**. It is the intraday analogue of "buy confirmed strength, sized by volatility,
don't churn." Lowest frequency, highest per-trade edge — the right place to start when costs are the
enemy.

```yaml
# config/strategies/m1.yaml  — micro control (sketch; every leaf calibrated by the backtester)
micro:
  interval_min: 5
  universe_size: 16
  eligibility: { min_dollar_vol_m: 50, max_spread_bps: 5, atr_pct_min: 1.5, atr_pct_max: 5.0 }
  gate:
    rvol_min: 1.8
    min_edge_mult: 2.0            # target must be >= 2x round-trip cost (§3.2)
    last_entry_time: "15:25"      # ET
    eod_flat_time: "15:55"        # ET — hard force-flat, never hold overnight
  legs:
    eod_momentum:  { enabled: true,  open_window_min: 30, lookback_sessions: 5 }
    vwap_trend:    { enabled: true,  stop_atr: 1.5 }
    vwap_reversion:{ enabled: false }   # off in m1
    orb:           { enabled: false }   # off in m1
scoring:
  rank_normalize: true            # rank the micro pool cross-sectionally, like the daily sleeve
```

### `m2` — the contrast: **ORB instead of EOD/VWAP-trend** (one variable: the entry pattern)

**The single difference:** `m2` turns **off** the EOD-momentum + VWAP-trend legs and turns **on
Opening-Range Breakout** (with the *same* RVOL gate, cost gate, time gate, sizing, and force-flat).
This isolates the cleanest, most decision-relevant question for a day-trading system:

> **Does a low-win-rate / high-R:R breakout pattern (ORB) beat a higher-win-rate / lower-R:R
> trend-continuation pattern (EOD+VWAP) on this universe, after costs?**

That is the intraday equivalent of the daily sleeve's momentum-vs-reversion meta-decision, and it's a
**single, clean variable** (entry pattern), holding the entire cost/risk/exit framework constant — so
the A/B verdict is interpretable.

```yaml
# config/strategies/m2.yaml  — = m1 with ONLY the entry legs swapped
micro:
  legs:
    eod_momentum:  { enabled: false }
    vwap_trend:    { enabled: false }
    orb:           { enabled: true,  or_minutes: 15, range_mult: 2.0, stop_atr: 1.5 }
# everything else (gate, sizing, force-flat, rank_normalize) inherited from base — unchanged
```

### Measurement (mirrors v3/v4 discipline)

- **Arms:** `m1` (control) vs `m2` (delta = ORB), each on a `micro-500` and a `micro-100k` portfolio,
  compared on `/compare` by **net-of-cost** NAV / P&L / hit-rate / profit-factor.
- **Commissions + slippage ON** (P10) — a commission-free intraday A/B is meaningless.
- **Verdict needs many *trading days* of forward paper, not a deep historical backtest** (§4.1: the
  free intraday history is too shallow). Pre-register the criterion before running, as v4 did.
- **Track the cost ratio explicitly:** report **gross edge, total cost, net edge** per version. The
  most likely honest outcome — and the one the report must not hide — is that **both clear costs in
  paper at 0 commission but go net-negative once a realistic spread+commission is charged**, which
  itself is the most valuable finding: it tells the owner whether micro is worth a real-broker seam.

---

## Handoff notes

**What this document produced:** a grounded intraday-strategy catalogue (VWAP trend/reversion, ORB,
RVOL gate, EOD momentum, intraday mean-reversion, gap-and-go) with entry/exit/stop rules, horizons and
realistic *pre-cost* hit-rates; a day-tradeable **micro universe** spec (static eligibility + a morning
RVOL ranker) recommending a **tight ~12–20 symbol subset** of the existing watchlist; a **cost-first
sizing model** (the spread+commission break-even math, fractional shares, 1–2 vs 3–6 concurrent
positions, and the PDT/SSR real-world caveats); an **indicator-level mapping** that reuses the
`Indicator`/`score_universe`/`PaperBroker` seam unchanged and specifies the **new indicators**
(AnchoredVWAP, OpeningRange, RelativeVolume, GapPercent) + a **new `intraday_bars` hypertable** + a
**`run_micro` interval job**; and a concrete **`m1` (control) / `m2` (ORB contrast)** version pair under
the one-variable discipline.

**What the implementation plan / downstream agents need from me:**
- **Database Optimizer:** new `intraday_bars` hypertable PK `(symbol, ts, interval)` with **compression
  + retention** (5m≈90d, 1m≈14d) — this is the one table that grows the Pi materially; cap it.
- **Data Engineer:** chain yfinance-intraday → Finnhub → Twelve Data behind `MarketDataProvider`;
  **trade/backtest on 5m/15m, not 1m** (1m history ≈ 7 days); **poll cadence ≥ 5 min** (free-tier +
  Pi). Build AnchoredVWAP/OpeningRange/RelativeVolume/GapPercent as thin `Indicator` subclasses.
- **Backend Architect / Workflow Architect:** a market-hours `run_micro` `IntervalTrigger` (the
  `protective_sell` pattern), a morning `rank_micro_universe`, and a **hard EOD force-flat** — micro
  never holds overnight; all idempotent; `kind='micro'` portfolios, seam untouched.
- **Experiment Tracker:** micro verdicts come from **forward paper days**, not deep backtests (history
  is too shallow); **always run with commissions+slippage ON**; report gross/cost/net edge separately.

**Open questions (deferred to the implementation plan / Experiment Tracker):**
1. **RVOL as gate vs weight** — recommended as a multiplicative *gate* in a micro action layer (not a
   `scoring.weights` entry). Confirm the cleanest seam placement (mirror the daily `market_filter`).
2. **Calibration of every threshold** (`rvol_min`, `min_edge_mult`, `or_minutes`, ATR stops,
   `universe_size`) — stubs here; the backtester/forward-paper sets them. **Do not hand-tune.**
3. **Is micro worth a real seam at all?** The cost math (§3.2) suggests the realistic net edge on
   €500-scale tickets is **near or below zero after real spreads**. The paper A/B should answer this
   *before* any Phase-2 intraday real-broker work is even scoped.
4. **Whether to model passive (limit-at-VWAP) fills** later — Phase 1 assumes **marketable fills with
   explicit slippage**; passive-fill modeling is a known overstatement risk, deferred.
5. **Shorting** — paper allows it; ORB/VWAP short legs are **less transferable** (SSR/locate). Decide
   whether `m1`/`m2` run long-only first to keep the paper→real gap honest.
