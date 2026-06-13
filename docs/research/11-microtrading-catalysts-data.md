<!-- Agent: Trend Researcher | Phase: 0-micro | Depends on: docs/research/00-signal-synthesis.md, docs/architecture/data-ingestion.md -->

# Phase 0-micro — Intraday Catalysts, Sentiment & the Data-Feasibility Study

**Stream:** The day-trading equivalent of the news/sentiment/smart-money stream (`02-`). Where the existing system is a once-daily batch on EOD bars (1–4 week horizon), the proposed **microtrading** section opens and closes positions **within the same session** ("microinversiones diarias"). The edge, the data, and the failure modes are all different.

> Same three hard filters as every prior stream apply, plus one that dominates here:
> (1) computable from **free / free-tier** data, (2) cheap on **ARM64 / 4GB Raspberry Pi 4**,
> (3) backed by published evidence — **and (4) the alpha must survive a polling cadence the
> Pi and the free tiers can actually sustain.** A microtrading signal that only works on a
> live tick stream we cannot afford is worth zero. This document is deliberately honest about
> what is **not feasible for free on a Pi**, because the project's own memory records that the
> backtester showed the daily v1 control *beating* every v2–v6 "improvement". Microtrading
> multiplies turnover, commission drag (P10), and slippage — the bar for "this actually adds
> edge" is **higher** here, not lower.

> **Headline reality, established up front (verified June 2026):** the project brief assumed
> Finnhub would supply intraday candles because `FINNHUB_API_KEY` is already wired. **It will
> not.** Finnhub moved `/stock/candle` (intraday + historical OHLC) to its **premium tiers**;
> free keys now get **HTTP 403 "You don't have access to this resource"** on that endpoint.
> Finnhub free remains excellent for *quotes, company-news, profiles, basic financials* — but
> **not bars**. This single fact reorders the whole provider chain below (§2).

> Convention (unchanged from `02-`): **Horizon** = how long the edge lives. **Type** =
> Leading / Confirming / Filter. **Verdict** = Use / Selective / Avoid under the
> intraday-poll + free-tier + Pi constraints.

---

## SECTION 0 — Cadence reality: what "microtrading on a Pi" can and cannot be

Before any signal, fix the cadence, because it bounds everything else.

| Cadence model | What it needs | Feasible free on Pi? |
|---|---|---|
| **True tick / sub-second scalping** | Co-located low-latency feed, microsecond order routing | **No.** Not free, not on a Pi, not in Phase 1 (paper). Out of scope, permanently for this project's constraints. |
| **1-minute bar reaction** | A reliable 1m feed + a poll or websocket every 60s for ~50 symbols | **Marginal.** yfinance 1m exists but is rate-limited and fragile under tight polling; sustained 60s polling of 50 names risks throttling/bans. Possible for a *handful* of symbols, not the full 50. |
| **5–15-minute "micro-swing" / intraday momentum** | 5m/15m bars pulled every 5–15 min during RTH | **Yes — this is the realistic target.** Fits free-tier call budgets, fits the Pi's RAM/CPU, and still captures gap-fade, intraday momentum, and same-day catalyst drift. |
| **Open / close only (gap & MOC)** | One pull near 09:30 ET, one near 15:45 ET | **Trivially yes**, and a sensible *first* micro version. |

**Decision that frames the rest of the document: the microtrading section targets a
5-minute primary bar with a 5-minute poll during regular trading hours (RTH), with an
explicit pre-market gap scan and an end-of-day forced flat.** "Microtrading" here means
*same-day intraday momentum / gap trades on 5m bars*, **not** scalping. Anyone expecting
tick scalping should read §2.6 and §3 and recalibrate: it is not free, and it is not a Pi
workload.

---

## SECTION 1 — What moves prices intraday, and what we can detect

> The intraday edge, like the daily one, is *not* "a catalyst happened" — by the time a free
> 5m bar prints, the first impulse is gone. The intraday edge is in effects that **persist for
> minutes-to-hours within the session**: opening-gap continuation/fade, intraday momentum from
> abnormal volume, the post-news drift on the 30–120-minute scale, and index/sector beta
> dragging a basket. Each below is scored for *detectability on a 5m-poll cadence with free data*.

### 1.1 Intraday catalyst taxonomy

| Catalyst | Intraday price behaviour | Edge that survives to a 5m bar | Free-data detectable on 5m poll? | Verdict |
|---|---|---|---|---|
| **Pre-market gapper** (overnight news/earnings) | Large open gap; statistically tends to *continue* on high relative volume + *fade* on low-volume / exhaustion gaps | The continuation-vs-fade decision is made in the **first 15–60 min**, not the first tick | **Yes** — pre-market quote + first 5m bars + relative volume give gap %, gap direction, and early RVOL | **Use** — the single best free intraday setup |
| **Earnings during/after session** | Sharp gap + multi-hour drift (intraday PEAD) | Drift in the surprise direction over the **rest of the day** | Partly — we know *who* reports (`earnings_calendar`); we cannot get a clean intraday consensus-surprise free. Use the **price gap sign** as the proxy | **Selective** — trade the confirmed gap, not the number |
| **Intraday momentum / abnormal volume** | Sustained directional move once volume ≫ typical for the time-of-day | Momentum persists tens of minutes once RVOL is extreme | **Yes** — RVOL vs a same-time-of-day baseline is pure math on 5m bars | **Use** — second-best free setup |
| **Trading halt → reopen** (LULD, news pending) | Reopen auction often gaps again; high uncertainty | The reopen direction can drift | **Weakly.** Halt *status* needs a real-time feed (Finnhub free has *no* halt list; Nasdaq/NYSE halt feeds are scrape-only). On a 5m poll you'll see the gap but learn the *cause* late | **Selective / Avoid Phase 1** — detect the gap, don't chase the reopen |
| **Sector / index-driven move** (SPY/QQQ leg, sector ETF rotation intraday) | High-beta names track the index leg | Beta drag is persistent and *predictable* given the index move | **Yes** — we already pull SPY/QQQ/sector SPDRs; compute intraday beta-adjusted residual | **Use** — cheap, and a good *filter* (don't fight the tape) |
| **Halts for volatility on the watchlist's high-ATR names** (TSLA/NVDA/AMD type) | Repeated LULD pauses | Pure noise without the halt feed | No (free) | **Avoid** |
| **Index reconstitution / MOC imbalance** | Close-auction pressure | Last 15–30 min drift toward imbalance | Imbalance feed is **paid/intraday**; only the *price* footprint is free | **Avoid Phase 1** |

### 1.2 The three free, Pi-feasible intraday setups (the keepers)

1. **Opening-gap continuation/fade** — *Leading.* Inputs: overnight gap % (prev close → pre-market / first print), gap direction, and **early relative volume** (first 1–3 bars vs same-time historical). High-RVOL gaps in the trend direction continue; low-RVOL gaps fade to prior close. All computable from a pre-market quote + the first few 5m bars + a stored time-of-day volume profile. **Primary micro signal.**
2. **Intraday relative-volume momentum** — *Leading/Confirming.* Inputs: cumulative volume vs a **time-of-day-normalized** baseline (volume at 10:15 ET is meaningless without knowing typical 10:15 volume), plus VWAP position (above/below) and 5m momentum. Trade in the direction of an extreme-RVOL break of the opening range, exit on VWAP loss or fixed time. Pure 5m-bar math. **Secondary micro signal.**
3. **Index/sector beta filter** — *Filter, not alpha.* Compute each symbol's intraday move *minus* its expected move given SPY/QQQ/sector leg. Use it to (a) **suppress** longs when the tape is broadly down (mirrors the daily "wait for a good moment" market-entry filter at intraday scale) and (b) prefer names with *positive residual* strength. Reuses tickers we already ingest.

Everything else in §1.1 is either a *risk exclusion* (halts, earnings-into-the-print, MOC) or **Phase 2 / paid** (real-time halt feed, imbalance feed, unusual options flow — already Phase 2 in `02-`).

### 1.3 What is honestly NOT a free intraday edge on a Pi

- **Tape reading / order-flow / Level 2** — needs a depth-of-book feed (paid). Out.
- **Real-time unusual options flow** — already Phase 2 in `02-§3.3`; intraday + paid. Still out.
- **Real-time dark-pool prints / DIX** — paid; `02-§3.4`. Out.
- **Halt/reopen *as a signal*** — needs a live halt feed; free sources are scrape-fragile. Detect the gap, do not trade the reopen, Phase 1.
- **Sub-minute anything** — not a Pi/free workload, full stop.

---

## SECTION 2 — INTRADAY DATA SOURCES (the crux)

This is where the project's assumptions need the most correction. The brief named yfinance
intraday + Finnhub + Twelve Data behind the `MarketDataProvider` Protocol with a fallback
chain. The Protocol pattern is right; **the assumed roles are wrong**, chiefly because
Finnhub free no longer serves bars.

### 2.1 Per-provider intraday capability (verified June 2026)

| Provider | Intraday granularities | Historical depth (intraday) | Rate limit (free) | WS vs REST | ARM/Pi notes | Bars on FREE tier? |
|---|---|---|---|---|---|---|
| **yfinance** (Yahoo, unofficial) | 1m, 2m, 5m, 15m, 30m, 60m/1h, 90m | **1m ≈ last 7 days; all other intraday ≈ last 60 days** | No published quota; **soft IP throttling / intermittent bans** under aggressive polling (worsened 2024–2025) | REST-ish scrape (batched `download`) | Already in the stack, ARM-fine; **fragility, not CPU, is the risk** | **Yes** (but fragile) |
| **Finnhub** | `/stock/candle` supports 1/5/15/30/60m | n/a on free | 60 calls/min (generous) **but candles are 403** | REST; WS exists (trades) but candles gated | Already keyed in `.env`; **good for news/quotes, NOT bars** | **NO — `/stock/candle` is premium (403)** |
| **Twelve Data** | 1min, 5min, 15min, 30min, 45min, 1h… | Generous on paid; **free is credit-bounded** | **8 calls/min, 800 credits/day**; WS = credits-per-symbol | REST + **WebSocket on free** (credit-metered) | Already the EOD fallback; ARM-fine | **Yes** (within 800/day) |
| **Alpaca Market Data** (IEX feed) | 1Min, 5Min, 15Min, 1H, 1D bars | Multi-year history on bars; **SIP needs end ≥15 min old** without sub; **IEX feed is free** | "Limited" historic calls + WS on free; ~200 req/min typical on Basic | REST **and WebSocket (free, IEX)** | Needs API key+secret (free paper acct); ARM-fine, official SDK | **Yes — IEX bars free** (IEX ≈ 2–3% of volume, so partial tape) |
| **Alpha Vantage** intraday | 1/5/15/30/60min | ~2 years (paid); free is throttled | **25 req/day** (brutal — same as `02-`) | REST | unusable at scale | **No (effectively)** — 25/day |
| **Polygon.io** | full intraday | years | Free tier = **5 req/min, EOD only** now | REST+WS (paid) | — | **No (free intraday removed)** |

### 2.2 The corrected provider verdicts

- **yfinance intraday = primary bar source, but rate-limit-disciplined.** It is the only
  free source that gives 5m/15m bars *with ~60 days of rolling history* and no key. Its
  weakness is **aggressive-polling fragility**: do not hammer it every 60s for 50 symbols.
  Batched 5m polls every 5 min for ≤50 symbols is within tolerance *if* we add jitter,
  backoff, and a single-flight guard.
- **Alpaca (IEX feed) = the recommended *robust* primary/co-primary** and the biggest
  addition this study makes to the brief. It is **free, has a real WebSocket, multi-year
  intraday bar history, an official ARM-OK SDK, and is the same vendor the project will use
  for the Phase-2 real broker** — so wiring it now doubles as broker-seam groundwork. The
  catch: the free feed is **IEX-only** (~2–3% of consolidated volume), so its *volume* numbers
  are a fraction of true tape and its *prints* can be thin on illiquid names. For our 50-symbol,
  liquid, large-cap watchlist this is **acceptable for momentum/RVOL direction** (RVOL is
  computed against an IEX-consistent baseline, so the ratio still works), and its *price* is
  fine. Flagged limitation, not a blocker.
- **Twelve Data = the *bounded* fallback.** 800 credits/day means **~16 full-watchlist
  (50-symbol) refreshes per day** if each symbol is 1 credit — enough for a 15m cadence
  (≈26 RTH intervals) **only if batched** (multi-symbol per call) or scoped to a sub-universe.
  Its free **WebSocket** is the cleanest free push-feed but is **credit-metered per subscribed
  symbol**, so subscribing to 50 names continuously will burn the daily budget fast. Use Twelve
  Data REST as the *gap-filler when yfinance throttles*, not as the steady-state feed.
- **Finnhub = NOT a bar source.** Keep it exactly where `02-`/data-ingestion put it: news,
  quotes, profiles, financials. A single `/quote` call is fine for a *last-price* sanity check.
- **Alpha Vantage / Polygon free = unusable for intraday at our scale.** Note and move on.

### 2.3 Recommended fallback chain

```
INTRADAY BARS (5m, RTH):
  1. yfinance 5m batched download         ← primary (free, 60d history, no key)
        │  on RateLimitError / empty frame / stale
        ▼
  2. Alpaca IEX 5Min bars (REST)          ← robust fallback (free key, real history)
        │  on auth/quota error
        ▼
  3. Twelve Data 5min (batched REST)       ← bounded fallback (8/min, 800/day)
        │  exhausted
        ▼
  4. degrade: skip this poll, keep last good bars, mark intraday_completeness↓
             (NEVER block — mirrors the daily pipeline's degrade-don't-fail rule)

LAST PRICE / SANITY:
  Alpaca latest-quote  →  Finnhub /quote  →  yfinance fast_info
```

This is the **single-hop-per-stage** pattern the existing `ingest.py` already uses, extended
to a 3-deep chain because intraday throttling is far more likely than the daily case. Each hop
is the same `IntradayBarsProvider` Protocol (§5). **Every stage degrades to "keep last good +
mark incompleteness" rather than aborting** — identical to the project rule that a missing
provider key skips cleanly.

### 2.4 Recommended polling cadence (respecting free tiers + Pi budget)

| Phase of session (ET) | Job | Cadence | Symbols | Why |
|---|---|---|---|---|
| 09:00–09:30 pre-market | `scan_premarket_gaps` | once (~09:25) | full watchlist | Gap %, pre-market RVOL → today's micro candidate set |
| 09:30–16:00 RTH | `poll_intraday_bars` | **every 5 min** | candidate sub-universe (gappers + high-RVOL, typically ≤15) | 5m bars + RVOL + VWAP; only poll names that *qualified*, not all 50 |
| 09:30–16:00 RTH | `run_intraday_analysis` | every 5 min (after poll) | same | score → intraday BUY/SELL/FLAT |
| 15:45 ET | `force_flat_eod` | once | all open intraday positions | same-day mandate: never hold a micro position overnight |

**Call-budget math (the feasibility check):**
- RTH ≈ 6.5 h = **78 five-minute intervals**.
- Polling a **candidate sub-universe of ~15** symbols (not the full 50) batched into 1–2
  yfinance `download` calls/interval ⇒ **~80–160 yfinance calls/day** — comfortably under the
  throttling line *with jitter+backoff*.
- If yfinance throttles and we fail over to **Twelve Data**: 15 symbols batched ~2/call ⇒
  ~8 calls/interval × 78 = **~600+ credits** — **over budget for a full day**, so Twelve Data
  can only cover a *fraction* of the session as a stopgap. This is exactly why it is fallback #3,
  not the steady feed.
- **Alpaca IEX** has no daily-credit cliff like Twelve Data, so sustained 5m polling of 15
  symbols (~234 calls/day) sits inside Basic limits — reinforcing Alpaca as the robust fallback.

**Critical design choice: poll a *candidate sub-universe*, not the whole 50.** The
pre-market gap scan + an RVOL screen narrow 50 → ~5–15 names worth watching intraday. Polling
only those keeps every free tier in budget and the Pi's CPU idle most of each interval. Polling
all 50 every 5 min is the thing that gets yfinance banned and blows Twelve Data's 800/day.

### 2.5 Pi RAM/CPU budget for intraday

| Item | Estimate | Budget note |
|---|---|---|
| 5m bars, 15 symbols, 1 session (78 bars) in memory | ~a few hundred KB | trivial |
| Rolling 60-day 5m history for RVOL baselines, 50 symbols | ~50 × 78 × 60 ≈ 234k rows | small; lives in DB, queried windowed |
| Poll job RAM peak | well under the scheduler's ~400 MB analysis peak | fits the CLAUDE.md budget |
| WebSocket (if Alpaca WS used) | 1 persistent connection, low CPU | fine, but adds a long-lived task to the scheduler — see §2.6 |

The intraday workload is **I/O-bound (network polling), not CPU-bound**, so it sits inside the
existing performance budget. The risk to the budget is **a websocket holding a connection +
an in-memory tick buffer**, not bar polling.

### 2.6 REST polling vs WebSocket — recommendation

**Start with REST polling, not WebSocket.** Reasons: (a) the existing scheduler is a
batch/interval model (`protective_sell` already proves the interval-job pattern), and a 5m
REST poll slots straight into it; (b) a websocket is a long-lived stateful connection that
must reconnect, heartbeat, and buffer — more failure surface on a Pi that may sleep/restart;
(c) free websockets (Twelve Data credit-metered, Alpaca IEX) don't buy us much at a 5m
decision cadence — we don't need every tick, we need a clean 5m bar. **WebSocket is a Phase-2
optimization** if we ever go to 1m decisions; at 5m, polling wins on simplicity and matches the
project's "services communicate through the DB, jobs are idempotent" architecture.

---

## SECTION 3 — The backtest-data problem (be honest)

This is the section the project's memory (`v1 beats the improvements`) demands we treat with
discipline.

### 3.1 The hard limitation

**Intraday history is short and non-archival on free sources.** yfinance gives **only ~60
days of 5m bars and ~7 days of 1m** — and that window *rolls forward*, so you cannot pull
"5m bars for 2023." Twelve Data/Alpaca have deeper intraday history but free Twelve Data is
credit-throttled and Alpaca IEX history, while multi-year, is **IEX-only volume** (so RVOL
backtests are on a partial tape). **There is no free way to backtest an intraday strategy over
multiple years and full regimes.** Any micro version calibrated on 60 days of bars is fit to
*one* market regime (e.g., a single trend or chop) — precisely the overfitting trap that
produced v2–v6 losing to v1.

### 3.2 The four honest options, ranked

1. **Store intraday bars going forward — build our own history (RECOMMENDED).** Add the
   `intraday_bars` hypertable (§5) and have `poll_intraday_bars` persist every 5m bar from
   day one. After ~3 months we own ~3 months of *our actual* 5m tape across all regimes the
   market gave us; after a year, a real corpus. This is the only path that yields an
   **honest, growing, free** backtest set. Cost: patience — no real intraday backtest until
   weeks of data accrue.
2. **Rolling forward-test in paper (RECOMMENDED, in parallel with #1).** Because the whole
   project is *already paper*, the cleanest validation for a micro version is to run it live in
   a dedicated micro **portfolio** (the multi-portfolio model already supports this — spin up a
   `micro-500` portfolio with its own `strategy_label`) and compare its NAV/P&L/alpha against
   the daily-swing portfolios over the *same* live window. This is forward-testing with real
   (paper) fills, slippage proxy, and commission (P10) — the most truthful signal we can get,
   and it sidesteps the short-history problem entirely.
3. **Short-window backtest with explicit regime caveat (ACCEPT, with discipline).** Use
   yfinance's 60 days of 5m as a *sanity check only* — "does the logic execute, are fills
   plausible, is turnover sane" — **never** as evidence the edge is real. Tag every such result
   "single-regime, 60d, not validation." The backtester (`backend/backtest/`) replays the live
   pipeline; an intraday mode would replay 5m bars the same way, but the data window makes its
   *statistical* output untrustworthy.
4. **Paid intraday history (DEFER / Phase 2).** Polygon/Alpaca-SIP/Tiingo sell years of
   minute bars. Only worth it once forward-testing (#2) shows a micro version is *plausibly*
   profitable and we want a multi-regime confirmation before scaling. **Do not buy history to
   discover an edge; buy it to confirm one.**

### 3.3 The verdict

> **Backtest verdict:** there is **no free, multi-regime intraday backtest** available, and a
> 60-day single-regime backtest is exactly the overfitting that already burned v2–v6.
> Therefore the discipline for microtrading is: **(a) start persisting our own 5m bars
> immediately (#1) to grow a real corpus, (b) validate by forward-testing a dedicated micro
> *paper portfolio* against the daily ones (#2), and (c) treat any 60-day yfinance backtest as
> a logic/plumbing sanity check, never as proof of edge.** No micro version ships to a funded
> (paper) portfolio on the strength of a short backtest alone — same calibration discipline the
> Experiment Tracker enforces for daily versions, applied even more strictly because intraday
> turnover amplifies commission/slippage drag.

---

## SECTION 4 — Intraday sentiment & news: what adds edge, what is too slow

> The daily stream (`02-`) found Finnhub company-news + EDGAR 8-K/Form-4 + market-wide
> VIX/put-call useful at the *daily* horizon. Intraday is harsher: most of those are **too slow
> or too coarse** to help a 5m decision. Mapped onto the existing Protocol pattern below.

| Source | Intraday usefulness | Latency vs a 5m bar | Verdict |
|---|---|---|---|
| **Finnhub `/company-news`** (already wired) | The headline that caused the gap is usually *already in the gap*; news arrives in batches, not real-time-tagged on free | Minutes-to-hours; not tick-aligned | **Selective** — use as a *context flag* on a gapper ("was there overnight news?"), **not** an entry trigger |
| **Pre-market movers / gap list** | **High** — this *is* the micro candidate generator | Available ~pre-open | **Use** — but derive it ourselves from pre-market bars/quotes (Alpaca pre-market, or yfinance pre/post via `prepost=True`), not a paid "movers" API |
| **Finnhub `/quote`** (real-time last) | Useful as a price/last-trade sanity and a cheap pre-market level | Real-time-ish | **Use** as the sanity-price leg of the fallback chain |
| **Earnings calendar** (already a table) | Knowing *who reports today/after-hours* gates which names are event-locked vs tradeable | Known in advance | **Use** as an **exclusion/awareness filter** (don't micro-trade into the print) |
| **SEC 8-K (EDGAR)** | The 8-K is the *authoritative* version of the catalyst but posts within hours, often after the move | Too slow for intraday entry | **Avoid for intraday timing** (keep it for the daily system) |
| **VIX / market-wide put-call** | Sets intraday *risk posture* (high VIX ⇒ wider stops, smaller size), same as daily | Daily value, intraday VIX via `^VIX` 5m | **Use** as a sizing/regime knob, not a per-name signal (mirrors daily) |
| **Social (Reddit/StockTwits/Trends)** | Attention spikes correlate with intraday volume/vol, **not** clean direction; scrapers are fragile and rate-limited — worse intraday | Noisy, laggy, fragile | **Avoid Phase 1** (already Selective/Avoid in `02-`; intraday makes it worse) |
| **Real-time news-sentiment APIs** (Benzinga, etc.) | Genuinely useful intraday but **paid** | Real-time (paid) | **Phase 2** |

**Net:** the only *news/sentiment* inputs that earn their place in the micro loop are
**(1) the self-derived pre-market gapper/RVOL list** (the candidate generator), **(2) a
Finnhub news/quote context+sanity flag**, and **(3) the earnings-calendar exclusion**. The
intraday edge is overwhelmingly **price+volume structure**, with news as *context*, not
trigger — the opposite emphasis from a swing system. Everything heavier is too slow, too
noisy, or paid.

---

## SECTION 5 — Data-ingestion design sketch (interfaces, not code)

Described at the level of `docs/architecture/data-ingestion.md` — Protocols, tables,
job wiring, idempotency — leaving business logic as stubs per the project rules.

### 5.1 New Protocol — `IntradayBarsProvider`

Lives in `backend/data_ingestion/protocols.py` alongside the existing providers. **It does
not replace `MarketDataProvider`; it's a sibling sub-protocol**, keeping daily and intraday
ingestion swappable independently.

```
IntradayBarsProvider (Protocol)
  get_intraday_bars(symbols, interval, start, end) -> Mapping[str, list[IntradayBar]]
  get_premarket_quote(symbols) -> Mapping[str, Quote]        # gap-scan input
  get_latest_price(symbols) -> Mapping[str, Decimal]         # sanity / WS-less last
```

- `IntradayBar` = frozen pydantic DTO mirroring `OHLCVBar` **plus** `interval` and a
  `session` tag (`pre` / `rth` / `post`). UTC timestamps, same as the daily DTO.
- Adapters (all behind this one Protocol, selected by `INTRADAY_DATA_PROVIDER`, chained per §2.3):
  `YFinanceIntradayProvider` (primary), `AlpacaIntradayProvider` (robust fallback, IEX feed),
  `TwelveDataIntradayProvider` (bounded fallback — extend the existing Twelve Data adapter with
  an interval param). Each raises `RateLimitError` to trigger the next hop — reusing the
  existing `errors.py`.
- `get_available_symbols` returns `[]` — **watchlist stays runtime-populated** (CLAUDE.md).

### 5.2 New table — `intraday_bars` (hypertable)

| Column | Notes |
|---|---|
| `symbol` | FK-ish to watchlist (runtime) |
| `ts` | UTC bar-open timestamp |
| `interval` | `'5m'` etc. — part of natural key (lets us store 1m + 5m without collision) |
| `open/high/low/close` | Decimal |
| `volume` | bigint; **IEX-partial when sourced from Alpaca — record `source`** |
| `source` | provider that produced it (yfinance/alpaca/twelvedata) — for the IEX-volume caveat |
| `session` | pre/rth/post |

- **Hypertable** partitioned on `ts`, **composite PK `(symbol, ts, interval)`** — same
  idempotent `INSERT … ON CONFLICT DO UPDATE` pattern as `market_bars`. Re-running a poll
  overwrites in place; **no duplicates** (CLAUDE.md mandate).
- **Volume is tiny by Pi standards:** 50 symbols × 78 5m bars/day ≈ **3,900 rows/day** ≈
  ~1M rows/year — well inside the budget; TimescaleDB compression on bars older than N days
  keeps it flat. (We'll usually poll ≤15, so real volume is lower.)
- Optional sibling `intraday_volume_profile` (time-of-day mean/σ volume per symbol) materialized
  from `intraday_bars` for RVOL baselines — or compute on the fly with a continuous aggregate.

### 5.3 New jobs (scheduler)

Registered as **interval triggers gated to RTH**, exactly like the existing `protective_sell`
job — *not* in the daily `JOB_SCHEDULE`. All `misfire_grace_time` short (a missed 5m poll is
stale, don't backfill-trade it).

| Job | Trigger | Gate | Action |
|---|---|---|---|
| `scan_premarket_gaps` | cron ~09:25 ET (market days) | `is_trading_day` + `INTRADAY_ENABLED` | pre-market quotes → gap%/RVOL → write today's `intraday_candidates` |
| `poll_intraday_bars` | interval `INTRADAY_POLL_MIN` (default 5), RTH only | trading-day + RTH window + `INTRADAY_ENABLED` | fetch 5m bars for the candidate sub-universe via the fallback chain → idempotent upsert |
| `run_intraday_analysis` | interval, RTH, after poll | as above + `MICRO_STRATEGY` active on ≥1 portfolio | compute gap/RVOL/VWAP signals → intraday score → BUY/SELL/FLAT per micro portfolio |
| `force_flat_eod` | cron ~15:45 ET | trading-day + `INTRADAY_ENABLED` | close every open intraday position (same-day mandate) |

- **All gated by `INTRADAY_ENABLED` (default false)** and **skip cleanly when the chain's keys
  are absent** (Alpaca key missing ⇒ that hop is skipped, never a crash) — identical to the
  `FRED_API_KEY`/`FINNHUB_API_KEY` degrade rule.
- **Single-flight guard** per interval (the API already has the pattern for `POST
  /api/system/run`) so overlapping polls can't double-fetch.

### 5.4 The BrokerAdapter seam stays sacred

Microtrading generates *more* orders, not different ones. `run_intraday_analysis` produces
ranked intraday candidates; **`PortfolioManager` (not the analysis) calls
`BrokerAdapter.place_order`** with `qty: Decimal` — same fractional-share seam, same
`PaperBroker`. A micro portfolio is just another `portfolios` row with its own
`strategy_label` (e.g. `micro-v1`) and cash. **No change to the four sacred Protocol methods.**
`force_flat_eod` sells via `place_order` like `protective_sell` already does. The seam swap to
a real broker (Phase 2) is unaffected — and choosing **Alpaca** as the intraday data fallback
*aligns* with the likely Phase-2 `BROKER_ADAPTER=alpaca`, so one vendor relationship covers
both.

### 5.5 New config (env / strategy.yaml — nothing hardcoded)

```
INTRADAY_ENABLED            (default false)
INTRADAY_DATA_PROVIDER      (default yfinance; chain order configurable)
INTRADAY_INTERVAL           (default 5m)
INTRADAY_POLL_MIN           (default 5)
INTRADAY_RTH_TZ / window    (market-hours gate)
ALPACA_API_KEY / SECRET     (free paper key; fallback hop skips if absent)
ALPACA_DATA_FEED            (default iex)
PREMARKET_GAP_MIN_PCT       (candidate-screen threshold — stub)
INTRADAY_RVOL_MIN           (candidate-screen threshold — stub)
MICRO_MAX_HOLD_MIN          (force a time-based exit)
```

Micro-strategy weights/thresholds live in a **versioned overlay**
`config/strategies/micro-v1.yaml` deep-merged onto the base — same mechanism as v1–v6 — so the
micro section is A/B-comparable against itself and against the daily portfolios via the existing
`/compare` route. **Every threshold is config; none hardcoded.**

---

## Handoff notes

**What this document produced:** an intraday-catalyst taxonomy scored for free/Pi
detectability on a 5m cadence; a corrected, verified provider/fallback design for intraday
bars; an honest treatment of the short-history backtest problem with a forward-test-first
discipline; an intraday news/sentiment mapping; and a data-ingestion design sketch
(`IntradayBarsProvider` Protocol, `intraday_bars` hypertable, RTH interval jobs, idempotent
upsert) at the level of the existing `data-ingestion.md`, leaving logic as config-driven stubs.

**Key corrections to the project's stated assumptions:**
- **Finnhub free does NOT serve intraday (or historical) candles** — `/stock/candle` is
  premium, returns **403** on free keys (verified June 2026). Finnhub stays as
  news/quotes/financials only. The brief's assumption that the existing `FINNHUB_API_KEY`
  unlocks intraday bars is wrong; **plan accordingly.**
- **Add Alpaca (free IEX feed)** as the robust intraday-bar fallback — real WebSocket,
  multi-year history, official ARM-OK SDK, and it doubles as Phase-2 broker groundwork.
  Caveat: IEX-only volume (~2–3% of tape) — fine for direction/RVOL ratios on liquid large-caps,
  flagged for thin names.
- **Twelve Data is bounded** (8/min, 800 credits/day ⇒ ~16 full-watchlist refreshes/day) — a
  stopgap fallback, **not** a steady-state intraday feed.

**Decisions deferred to synthesis / downstream agents:**
1. **Cadence:** recommend 5-minute bars / 5-minute poll of a *candidate sub-universe* (≤15),
   not 1m and not all 50 — needs Workflow-Architect sign-off on the interval-job model.
2. **Backtest discipline:** forward-test a dedicated micro **paper portfolio** + persist our own
   5m bars to grow history; treat 60-day yfinance backtests as plumbing checks only — needs
   Experiment-Tracker ownership.
3. **Provider chain order** (`yfinance → Alpaca → Twelve Data`) and whether to adopt the Alpaca
   key now (it overlaps Phase-2 broker) — Software Architect + Data Engineer.
4. **DB:** new `intraday_bars` hypertable (PK `symbol, ts, interval`, `source` column for the
   IEX-volume caveat) + optional `intraday_volume_profile` — Database Optimizer.
5. **WebSocket vs REST:** recommend REST polling for Phase 1 (matches the batch/interval
   architecture); WebSocket is a Phase-2 optimization only if we move to 1m decisions.
6. **Scope honesty:** tick scalping, real-time halt/imbalance/options-flow feeds are **not free
   and not a Pi workload** — permanently out of Phase 1, consistent with `02-`'s Phase-2 line.
