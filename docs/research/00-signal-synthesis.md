<!-- Agent: Investment Researcher | Phase: 0B | Depends on: 01-technical-fundamental.md, 02-news-sentiment-smartmoney.md, 03-macro-intermarket-calendar.md -->

# Phase 0B — Master Signal Synthesis

**This is the single source of truth for the entire development.** Every Phase 1+ agent reads this first. It reconciles the three Phase-0A research streams into one prioritized, buildable plan: which signals to implement and in what order, where their data comes from, how they combine into one composite score, and what each downstream agent needs to know.

> **Primary prediction horizon: 1–4 weeks.** Technicals time the *when* (days–weeks), fundamentals set the *which* (weeks–quarters, applied as slow tilts), macro sets the *posture* (weeks–months, applied as a global multiplier). Everything below is filtered through three hard constraints inherited from CLAUDE.md: (1) computable from **free / free-tier** data, (2) cheap on **ARM64 / 4GB Raspberry Pi**, (3) backed by **published evidence**, not folklore.

> **Three cross-stream corrections / decisions resolved here (read before anything else):**
> 1. **`alternative.me` is crypto-only** — it is NOT an equity sentiment gauge. The CLAUDE.md data-source table is wrong on this. We **do not** use it. The equity Fear & Greed concept is **rebuilt from components we already fetch** (VIX + put/call + breadth + momentum). See §4.
> 2. **PEAD / earnings surprise has single ownership:** the **fundamental signal set computes SUE**; the **news/event set consumes it as a decaying drift tag**. One computation, one stored value, two readers. No double-counting.
> 3. **Two regime layers compose, they do not stack:** the **global macro regime** (RISK_ON/CAUTION/RISK_OFF) is a *post-multiplier* on the final score AND sets the *profile bias*; the **per-symbol regime classifier** (momentum vs reversion) only refines *within* the bias the macro layer hands down. Defined precisely in §3 and §4.

---

## SECTION 1 — SIGNAL PRIORITY MATRIX

All signals identified across the three streams, ranked by the five criteria in the brief (evidence strength, free availability, implementation complexity, alignment with our 1–4 week daily-batch horizon, and uniqueness / low correlation with signals already higher in the list).

**Legend** — Evidence: ★★★ strongest replicated anomaly · ★★ good published support · ★ weak/decayed/folklore. Availability: ✅ free & clean · ⚠️ free but thin/fragile · ❌ paid/intraday (Phase 2). Complexity: Low = pandas math · Med = new provider/scrape/parse · High = NLP/intraday/options-chain.

| # | Signal | Category | Evidence | Availability | Complexity | Tier |
|---|---|---|---|---|---|---|
| 1 | Blended cross-sectional momentum (3/6/12m ROC, 1m skip + 52w-high proximity + dual relative strength) | Technical | ★★★ | ✅ yfinance | Low | **1** |
| 2 | Per-symbol regime classifier (efficiency ratio + ADX + SPY/200d + VIX gate) | Technical (meta) | ★★ | ✅ yfinance | Low | **1** |
| 3 | Macro regime filter — RISK_ON/CAUTION/RISK_OFF (curve + VIX + VIX term + credit + breadth + SPY trend) | Macro (global) | ★★ | ✅ FRED+yfinance | Low | **1** |
| 4 | ATR(14) — volatility for position sizing & stops | Technical/risk | ★★★ (as risk tool) | ✅ yfinance | Low | **1** |
| 5 | Earnings & revenue **acceleration** (2nd-derivative YoY growth, 3 quarters) | Fundamental | ★★ | ✅ yfinance financials | Low | **1** |
| 6 | Quality composite (FCF yield + ROE trend + gross-margin trend) | Fundamental | ★★ | ✅ yfinance financials | Low | **1** |
| 7 | Trend gate (200d MA position + 50d slope) | Technical | ★★ (as filter) | ✅ yfinance | Low | **1** |
| 8 | Earnings calendar + de-risk window (scale down into report, up into PEAD) | Calendar | ★★ | ✅ yfinance | Low | **1** |
| 9 | SUE / earnings surprise (standardized) → **owns** the value PEAD consumes | Fundamental | ★★★ | ⚠️ consensus thin in yfinance | Med | **2** |
| 10 | PEAD decaying event tag (consumes #9, gated by day-1 reaction sign) | News/event | ★★★ | ⚠️ depends on #9 | Med | **2** |
| 11 | Analyst revision momentum (net EPS up/downgrades, 30/60d) | Fundamental | ★★★ | ⚠️ yfinance coverage spotty | Med | **2** |
| 12 | Insider Form 4 open-market **buying** (cluster + role-weighted) | Smart money | ★★★ | ✅ EDGAR/OpenInsider (free) | Med | **2** |
| 13 | 8-K material-event detection (item-code priors + keyword polarity) | News/event | ★★ | ✅ EDGAR EFTS (free) | Med | **2** |
| 14 | Sentiment momentum & divergence (Finnhub pre-scored, 3d-vs-14d z-score) | News/sentiment | ★★ | ⚠️ Finnhub free tier | Med | **2** |
| 15 | Market-wide contrarian sentiment composite (VIX level + VIX term structure + put/call) | Sentiment (global) | ★★ | ✅ yfinance + CBOE CSV | Low | **2** |
| 16 | Breadth ETF proxy (RSP/SPY, IWM/SPY) | Macro/breadth | ★★ | ✅ yfinance | Low | **2** |
| 17 | Sector rotation tilt (cycle phase → ±15% sector nudge, RS-confirmed) | Macro | ★ (noisy) | ✅ FRED+yfinance | Med | **2** |
| 18 | Short-interest trend + days-to-cover | Sentiment/positioning | ★★ | ⚠️ FINRA bi-monthly lag | Med | **2** |
| 19 | Sector-relative valuation (P/E z-score within sector; P/B asset-heavy; EV/EBITDA capital-intensive) | Fundamental | ★★ | ✅ yfinance (relative only) | Med | **2** |
| 20 | OBV divergence + volume-surge confirmation | Technical | ★ | ✅ yfinance | Low | **2** |
| 21 | RSI(14) regime-conditioned + BB-width squeeze | Technical | ★★ (regime-dep.) | ✅ yfinance | Low | **2** |
| 22 | Intermarket confirmation (HYG/IEF credit, copper/gold, dollar UUP, EEM stress) | Macro/intermarket | ★★ | ✅ yfinance | Low | **2** |
| 23 | Calendar/seasonal tilts (Halloween, September; rest default 0.0) | Calendar | ★ (mostly decayed) | ✅ date math | Low | **2** |
| 24 | Distress event flags (dividend cut, SEC/legal overhang, demand-driven layoffs) | News/event | ★★ | ⚠️ news NLP-ish | Med | **3** |
| 25 | News NLP beyond pre-scored APIs (transcripts, guidance parsing) | News | ★★ | ⚠️ heavy on Pi | High | **3** |
| 26 | Retail attention (Reddit/StockTwits/Google Trends) | Sentiment | ★ | ⚠️ fragile scrapers | Med | **3** |
| 27 | 13F institutional ownership changes | Smart money | ★ (stale) | ✅ EDGAR (45d lag) | Med | **3** |
| 28 | Dark-pool / ATS volume | Smart money | ★ | ⚠️ FINRA 2-wk lag | Med | **3** |
| 29 | Unusual options flow / per-symbol skew & IV | Smart money | ★★ (intraday) | ❌ paid + intraday | High | **3** |
| 30 | FOMC pre-drift tilt | Calendar | ★ (decayed) | ✅ date math | Low | **3** |
| 31 | OpEx gamma / max-pain pinning | Calendar | ★ (folklore) | ❌ needs options OI | High | **3** |

### Tier summary

- **Tier 1 (ship first — high evidence, free, low complexity, horizon-aligned):** blended momentum, per-symbol regime classifier, macro regime filter, ATR sizing, earnings/revenue acceleration, quality composite, trend gate, earnings de-risk calendar. These are 100% yfinance/FRED and need no NLP, no scraping, no new providers beyond OHLCV + financials + FRED.
- **Tier 2 (ship second — good evidence, needs data engineering):** SUE/PEAD pair, analyst-revision momentum, insider buying, 8-K detection, sentiment momentum/divergence, market-wide sentiment composite, breadth proxy, sector rotation, short-interest trend, sector-relative valuation, secondary technicals (OBV/RSI/BB), intermarket confirmation, seasonal tilts. These require new providers (EDGAR, Finnhub, CBOE, FINRA) behind the Protocol seam.
- **Tier 3 (defer — powerful but complex/expensive/intraday):** distress NLP, transcript parsing, retail-attention scrapers, 13F, dark pool, unusual options flow, FOMC/OpEx micro-tilts. Most are Phase 2 (paid or intraday alpha).

> **Note on the brief's "Expected" lists:** the brief anticipated earnings surprises in Tier 1. We **split** it: earnings/revenue *acceleration* (fully free, clean) is Tier 1; SUE/*surprise* (needs reliable consensus, thin in yfinance) is Tier 2. This is the most important deviation and the reason §2 budgets a second fundamentals provider decision.

---

## SECTION 2 — DATA SOURCE MAP (Tier 1 + Tier 2)

For every Tier 1 and Tier 2 signal: retrieval method, fetch cadence, target DB table, and per-symbol-per-year volume estimate (for Database Optimizer sizing). Volumes assume a ~50-symbol watchlist.

### 2.1 Tier 1 sources

| Signal | Library / endpoint | Cadence | DB table | Volume / symbol / yr |
|---|---|---|---|---|
| Blended momentum, trend gate, ATR, OBV, RSI, BB | `yfinance` daily OHLCV (`Ticker.history`) | Daily batch | `market_bars` (hypertable) | ~252 rows (1 bar/day) |
| Per-symbol regime classifier | derived from `market_bars` (no fetch) | Daily (compute) | `signal_values` | ~252 rows × signal |
| Macro regime filter — rates/curve/inflation/LEI/claims | `fredapi` / FRED REST (`DGS2,DGS10,DGS3MO,T10YIE,DFEDTARU,CPIAUCSL,PPIACO,PCEPI,USSLIND,MANEMP,PAYEMS,IC4WSA,UMCSENT`) | Daily pull (series update on their own cadence) | `macro_series` | ~13 series total; few-thousand rows for *years* (<1 MB) |
| Macro regime — VIX/term/credit/breadth/intermarket ETFs | `yfinance` (`^VIX,^VIX3M,^VVIX,HYG,IEF,TLT,LQD,USO,GLD,CPER,DBC,UUP,EEM,FXI,RSP,IWM`) | Daily batch | `market_bars` (reuse — these are just tickers) | ~252 rows each |
| Earnings/revenue acceleration, quality composite (FCF/ROE/margin) | `yfinance` `income_stmt`, `balance_sheet`, `cashflow` (quarterly) | Quarterly refresh (poll daily, upsert on change) | `fundamentals_quarterly` | ~4 rows/yr × N line items |
| Earnings calendar + de-risk window | `yfinance` `get_earnings_dates()` / `calendar` | Daily refresh (watchlist only) | `earnings_calendar` | ~4 report dates/yr |

### 2.2 Tier 2 sources

| Signal | Library / endpoint | Cadence | DB table | Volume / symbol / yr |
|---|---|---|---|---|
| SUE / earnings surprise | `yfinance` actuals + estimates ⚠️ thin; **decision: budget Finnhub free tier** (`/stock/earnings`) for clean consensus | Quarterly (poll daily near report) | `earnings_estimates` | ~4 rows/yr |
| Analyst revision momentum | `yfinance` `recommendations`/`upgrades_downgrades` ⚠️; Finnhub `/stock/recommendation` as backstop | Weekly | `analyst_estimates` | ~12–52 rows/yr |
| Insider Form 4 buying | **OpenInsider** (`pandas.read_html`) for prototype; **SEC EDGAR** submissions JSON + Form 4 XML for hardened provider | Daily scan of last ~3 days | `insider_transactions` | ~5–40 rows/yr (event-driven) |
| 8-K material-event detection | **SEC EDGAR EFTS** (`efts.sec.gov/LATEST/search-index?forms=8-K`) + per-CIK submissions JSON | Daily scan of last ~5 days | `sec_filings` | ~10–30 rows/yr (event-driven) |
| Sentiment momentum & divergence | **Finnhub** `/company-news` (pre-scored) — primary | Daily (prior session) | `news_sentiment` | ~252 daily aggregate rows |
| Market-wide sentiment composite | VIX/term via `yfinance`; **CBOE** put/call daily CSV | Daily (T-1) | `market_sentiment` | ~252 rows (market-wide, not per-symbol) |
| Breadth ETF proxy | `yfinance` (`RSP,SPY,IWM`) ratios | Daily (compute) | `market_sentiment` (or `signal_values`) | ~252 rows |
| Sector rotation tilt | derived: FRED cycle phase + sector-ETF RS from `market_bars` | Daily (compute) | `signal_values` | small |
| Short-interest trend + days-to-cover | `yfinance` `.info` (convenience) + **FINRA** bulk file (accuracy/history) | Bi-monthly refresh | `short_interest` | ~24 rows/yr |
| Sector-relative valuation | `yfinance` `info`/`fast_info` (P/E, P/B, EV/EBITDA) → z-score within sector | Weekly | `fundamentals_quarterly` or `valuation_snapshot` | ~52 rows/yr |
| Intermarket confirmation | `yfinance` ETFs (already in `market_bars`) | Daily (compute) | `signal_values` | reuse |
| Seasonal/calendar tilts | pure date math + FOMC static config | Daily (compute) | none (config) | 0 |

**Aggregate DB-sizing takeaway for the Optimizer:** the dominant table by far is `market_bars` (50 watchlist + ~16 macro/intermarket tickers × 252 bars/yr ≈ 16.6k rows/yr — trivial). Everything else is event-driven (filings, earnings) or market-wide singletons (sentiment, macro). **Total annual write volume is well under a few hundred thousand rows — comfortable inside the Pi budget.** TimescaleDB compression matters only on `market_bars` over multi-year history.

**New tables implied (consolidated from all three streams):** `fundamentals_quarterly`, `earnings_calendar`, `earnings_estimates`, `analyst_estimates`, `insider_transactions`, `sec_filings`, `news_sentiment`, `market_sentiment`, `short_interest`, `macro_series`, plus `signal_values` (the universal computed-signal store). Intermarket ETFs reuse `market_bars` — **no new table**.

**Provider decision resolved:** accept yfinance for OHLCV + financials + fundamentals + earnings dates; **add Finnhub free tier** (60 calls/min) as the clean source for news sentiment AND consensus EPS / analyst recommendations (this is what unblocks SUE and revision momentum in Tier 2); **add SEC EDGAR** (no key) for Form 4 + 8-K; **add CBOE CSV** + **FINRA bulk** for market-wide put/call and short interest. FRED (one key) for all macro. No paid sources in Phase 1.

---

## SECTION 3 — COMPOSITE SCORING ARCHITECTURE PROPOSAL

> All weights, thresholds, and switches below are **stubs** — initial defaults to be calibrated by the Experiment Tracker after backtesting. Every value is a `config/strategy.yaml` key. The AI Engineer implements the *structure*; the numbers are configuration.

### 3.1 The scoring pipeline

```
Step 1  Per-symbol regime classifier  → {momentum | reversion} profile  (refines within macro bias)
Step 2  Technical score  (0–100)      = weighted avg of technical signals under the active profile
Step 3  Fundamental score (0–100)     = weighted avg of fundamental signals (acceleration, quality, valuation tilt)
Step 4  base_score = (Technical × w_tech + Fundamental × w_fund)        # w_tech + w_fund = 1.0
Step 5  Sentiment overlay (delta)     = news/sentiment nudge, bounded ±delta_cap
Step 6  composite_score = base_score + sentiment_delta + event_tags(PEAD, insider, 8-K)   # also bounded
Step 7  final_score = composite_score
                      × macro_regime_multiplier        # RISK_ON 1.1 / CAUTION 0.6 / RISK_OFF 0.3  (§4)
                      × sector_rotation_tilt            # ±15% per sector vs cycle phase
                      × calendar_size_factor            # earnings/FOMC/OpEx de-risking
```

`final_score` ranks the universe; the top-ranked names above a config cutoff become buy candidates, sized by ATR-based risk parity in `risk_manager`.

### 3.2 Initial weights (stubs)

At **daily / 1–4 week frequency, technicals lead.** Fundamentals move too slowly to time entries; they tilt *which* names qualify. Proposed defaults:

```yaml
scoring:
  weights:
    technical: 0.60        # momentum-dominant at our horizon
    fundamental: 0.40      # acceleration + quality + valuation tilt
  technical_profile:
    momentum:              # active when per-symbol regime = trending
      blended_momentum: 0.50
      trend_gate: 0.15
      relative_strength: 0.15
      volume_confirm: 0.10
      rsi_bb: 0.10
    reversion:             # active when per-symbol regime = choppy
      rsi_oversold: 0.35
      price_to_ma_atr: 0.25
      bb_squeeze: 0.20
      obv_divergence: 0.20
  fundamental:
    earnings_accel: 0.35
    quality_composite: 0.35   # FCF yield + ROE trend + margin trend
    sue_pead: 0.20            # Tier 2; 0 until consensus data wired
    valuation_relative: 0.10  # tiebreaker only
  sentiment_overlay:
    delta_cap: 10            # max ± points the sentiment overlay can move base_score
    news_momentum: 0.5
    news_divergence: 0.5
  event_tags:
    pead_max_bonus: 8        # decays over pead_window_days
    insider_cluster_bonus: 6
    sec_8k_polarity_max: 6   # signed: restatement negative, big-deal context
```

### 3.3 Missing-data handling (mandatory rules)

A daily multi-factor system MUST degrade gracefully — many symbols lack analyst coverage, news, or insider activity on any given day.

- **Renormalize, never impute zero.** If a signal is unavailable for a symbol, drop it from that symbol's weighted average and renormalize the remaining weights to sum to 1.0. A missing fundamental must not push the score toward the neutral midpoint and silently penalize well-covered names.
- **Category floor.** If an *entire category* is missing (e.g., no fundamentals for a brand-new ticker), score on the available categories and flag `data_completeness` so the ranker can optionally down-weight low-coverage names rather than corrupt the composite.
- **Event tags are additive and default-absent.** No PEAD/insider/8-K event = +0 (not negative). Absence of good news ≠ bad news.
- **Sentiment overlay defaults to 0** when no news exists — a name with no coverage is neutral, not penalized.
- Persist `data_completeness` (fraction of intended signals actually present) per symbol/date in `signal_values` for diagnostics and Experiment Tracker analysis.

### 3.4 Preventing single-signal domination

- **Cross-sectionally rank-normalize each raw signal** (percentile rank across the universe) before weighting, so an outlier in one raw metric can't blow out the composite. Z-scores **winsorized at ±3σ** as the alternative for signals with stable distributions.
- **Bound every additive component** (sentiment `delta_cap`, event-tag maxes) so overlays *nudge*, never override, the base score.
- **Bound the macro multiplier** to [0.3, 1.2] and the rotation tilt to ±15% — neither can flip the sign of a ranking, only scale it.
- The per-symbol regime classifier switches *profiles*, it does not add a separate score — preventing the regime read itself from becoming a dominating factor.

---

## SECTION 4 — MACRO REGIME CLASSIFICATION SPEC

The master switch. Outputs `RISK_ON | CAUTION | RISK_OFF`, applied as the §3.1 Step-7 multiplier AND as the profile bias the per-symbol classifier refines within. Built entirely from FRED + yfinance series we already store. **The equity Fear & Greed is reconstructed here** from VIX + put/call + breadth + momentum — we do NOT use alternative.me (crypto-only).

### 4.1 Inputs and votes

| Input | RISK_ON | CAUTION | RISK_OFF | Source |
|---|---|---|---|---|
| Yield curve 10Y−2Y | Normal/steepening (>0) | Flattening toward 0 | Inverted **then re-steepening** | FRED |
| Cycle phase (LEI + claims + MANEMP proxy) | Expansion | Peak | Contraction | FRED |
| VIX level | <20 | 20–30 | >30 | yfinance |
| VIX term structure (^VIX ÷ ^VIX3M) | <1 (contango) | ≈1 | >1 (backwardation) | yfinance |
| Credit (HYG/IEF) | Rising/stable | Drifting down | Falling fast (>stress%) | yfinance |
| Breadth (RSP/SPY) | Rising/broad | Narrowing | Falling hard | yfinance |
| SPY vs 200d MA | Above | Near/whipsaw | Below | yfinance |

### 4.2 The three states

| Regime | Trigger (strong condition fires it; else majority vote) | Behavior |
|---|---|---|
| **RISK_ON** | Curve normal **AND** cycle expansion **AND** VIX <20 **AND** credit stable | Aggressive: multiplier **1.1** (cap 1.2), full ATR-sized positions, **momentum profile** favored, full universe eligible |
| **CAUTION** | Curve flattening **OR** cycle = peak **OR** VIX 20–30 **OR** breadth narrowing | Reduce: multiplier **0.6**, smaller sizes, raise quality/defensive tilt, trim high-ATR names |
| **RISK_OFF** | VIX >30 **OR** VIX term ratio >1 **OR** credit widening fast **OR** SPY <200d MA | Defensive: multiplier **0.3** (toward cash), defensive sleeve (XLU/XLP/XLV) only, **reversion profile**, **suspend further de-risking when VIX >40** (panic = contrarian bottom — don't sell the capitulation) |

**Hysteresis:** a regime must hold **≥2 consecutive days** before the system switches, so a one-day VIX spike doesn't whipsaw the whole portfolio.

### 4.3 How the two regime layers compose (resolved)

The macro layer is **global and dominant**; the per-symbol layer is **local and subordinate**:

1. Macro regime sets the **multiplier** (Step 7) and the **profile bias**: RISK_ON → momentum bias, RISK_OFF → reversion/defensive bias, CAUTION → neutral.
2. The per-symbol classifier (efficiency ratio + ADX) then picks each symbol's profile **within that bias** — e.g., in RISK_ON, a choppy name can still score on the reversion profile, but the universe default leans momentum.
3. They **never both multiply the score.** Only the macro layer multiplies; the per-symbol layer only selects which technical weight-profile computes the Technical sub-score. No double-counting.

```yaml
regime:
  hysteresis_days: 2
  multipliers: { risk_on: 1.1, caution: 0.6, risk_off: 0.3 }
  multiplier_bounds: [0.3, 1.2]
  risk_off_panic_floor_vix: 40
  thresholds:
    vix_complacent_below: 20
    vix_caution_above: 20
    vix_stress_above: 30
    vix_panic_above: 40
    vix_term_structure_danger_ratio: 1.0
    curve_inversion_bps: 0
    curve_steepening_trigger_bps: 25
    real_rate_pressure_pct: 2.0
    credit_stress_drop_pct: 2.0
    breadth_rsp_spy_lookback_days: 63
    spy_trend_ma_days: 200
  rotation: { enabled: true, tilt_strength: 0.15, confirm_with_relative_strength: true, phase_confirm_reads: 2 }
```

---

## SECTION 5 — WATCHLIST FINAL (50 symbols)

Consolidated and trimmed from Stream 1's 62-symbol seed to the **50-symbol target**. Populated into the `watchlist` table at runtime from this seed (never hardcoded in source). Columns: **Categories** = which signal families apply best (T technical / F fundamental / M macro-sensitive) · **Data** = coverage (full = all signals available; gaps = expect missing fundamentals/news) · **Role** = alpha / hedge-defensive / benchmark.

### Benchmark & regime ETFs (5)

| Ticker | Name | Categories | Data | Role |
|---|---|---|---|---|
| SPY | S&P 500 | M | full | Benchmark / RS denominator / regime |
| QQQ | Nasdaq 100 | T, M | full | Growth-regime benchmark |
| IWM | Russell 2000 | T, M | full | Breadth/small-cap regime (IWM/SPY) |
| DIA | Dow 30 | M | full | Value/large benchmark |
| VIXY | VIX Short-Term | M | full | Fear gauge (regime input, not a held position) |

### Sector SPDRs (11) — rotation & relative-strength base

| Ticker | Sector | Categories | Data | Role |
|---|---|---|---|---|
| XLK | Technology | T, M | full | Alpha (rotation base) |
| XLC | Communication Services | T, M | full | Alpha |
| XLY | Consumer Discretionary | T, M | full | Alpha (cyclical) |
| XLF | Financials | T, F, M | full | Alpha (rate-sensitive) |
| XLV | Healthcare | T, F | full | Alpha / defensive sleeve |
| XLI | Industrials | T, M | full | Alpha (cyclical) |
| XLE | Energy | T, M | full | Hedge (low SPY corr, inflation) |
| XLB | Materials | T, M | full | Alpha (cyclical/commodity) |
| XLP | Consumer Staples | M | full | Defensive sleeve |
| XLU | Utilities | M | full | Defensive sleeve |
| XLRE | Real Estate | M | full | Defensive / rate-sensitive |

### Factor ETFs (3)

| Ticker | Factor | Categories | Data | Role |
|---|---|---|---|---|
| MTUM | Momentum | T | full | Factor-regime read / low-noise momentum |
| QUAL | Quality | T, F | full | Factor confirmation |
| VLUE | Value | T, F | full | Factor confirmation (value regime) |

### Single stocks (31) — alpha generators & signal test beds

| Ticker | Name | Sector | Categories | Data | Role |
|---|---|---|---|---|---|
| AAPL | Apple | Technology | T, F | full | Alpha — momentum + quality + PEAD anchor |
| MSFT | Microsoft | Technology | T, F | full | Alpha — quality/FCF + momentum |
| NVDA | NVIDIA | Technology | T, F | full | Alpha — high-ATR momentum + earnings accel |
| AVGO | Broadcom | Technology | T, F | full | Alpha — momentum + FCF yield |
| AMD | AMD | Technology | T, F | full | Alpha — high-vol momentum + PEAD |
| GOOGL | Alphabet | Comm Services | T, F | full | Alpha — momentum + valuation |
| META | Meta Platforms | Comm Services | T, F | full | Alpha — momentum + margin trend |
| NFLX | Netflix | Comm Services | T, F | full | Alpha — momentum + PEAD |
| AMZN | Amazon | Cons. Disc. | T, F | full | Alpha — momentum + operating leverage |
| TSLA | Tesla | Cons. Disc. | T | full | Alpha — extreme-ATR momentum + sentiment test |
| HD | Home Depot | Cons. Disc. | T, F | full | Alpha — cyclical + dividend quality |
| MCD | McDonald's | Cons. Disc. | F | full | Defensive-cyclical, low-vol |
| JPM | JPMorgan | Financials | T, F, M | full | Alpha — P/B value + rate sensitivity |
| BAC | Bank of America | Financials | F, M | full | Alpha — value + macro/rate |
| V | Visa | Financials | F | full | Alpha — quality/FCF compounder |
| BRK-B | Berkshire Hathaway | Financials | F, M | gaps (no analyst/PEAD) | Hedge — low-vol value anchor |
| UNH | UnitedHealth | Healthcare | T, F | full | Alpha — large-cap quality (non-biotech) |
| LLY | Eli Lilly | Healthcare | T, F | full | Alpha — momentum + earnings accel |
| JNJ | Johnson & Johnson | Healthcare | F | full | Defensive quality |
| CAT | Caterpillar | Industrials | T, F, M | full | Alpha — cyclical + PMI-proxy macro |
| GE | GE Aerospace | Industrials | T, F | full | Alpha — turnaround / revision momentum |
| HON | Honeywell | Industrials | F | full | Alpha — quality cyclical |
| XOM | Exxon Mobil | Energy | T, F, M | full | Hedge — commodity momentum + FCF yield |
| CVX | Chevron | Energy | F, M | full | Hedge — energy diversifier |
| COP | ConocoPhillips | Energy | T, M | full | Hedge — commodity beta |
| FCX | Freeport-McMoRan | Materials | T, M | full | Alpha — commodity/cyclical high-ATR |
| NEM | Newmont | Materials | M | gaps (commodity-driven) | Hedge — gold proxy (low SPY corr) |
| PG | Procter & Gamble | Cons. Staples | F | full | Defensive sleeve / low-vol |
| COST | Costco | Cons. Staples | T, F | full | Alpha — quality compounder |
| NEE | NextEra Energy | Utilities | M | full | Defensive / rate proxy |
| PLD | Prologis | Real Estate | M | gaps (FFO≠EPS) | Defensive — REIT rate-sensitivity test |

**Total: 5 + 11 + 3 + 31 = 50.** Coverage: all 11 GICS sectors, three cap tiers, every Tier-1/Tier-2 signal has ≥3 clean test beds. Annotated gaps (BRK-B, NEM, PLD) are intentional — they exercise the §3.3 missing-data renormalization path.

---

## SECTION 6 — WHAT EACH DOWNSTREAM AGENT NEEDS

### Software Architect (Phase 1)
- **New `MarketDataProvider` Protocol** must cover three shapes, not one: OHLCV bars, point-in-time fundamentals (quarterly statements), and event/series feeds (filings, macro series, sentiment). Consider sub-protocols: `OHLCVProvider`, `FundamentalsProvider`, `MacroProvider`, `NewsProvider`, `FilingsProvider`, `SentimentProvider` — all under `data_ingestion/providers/`.
- **`AnalysisEngine` Protocol** must expose the §3.1 pipeline as composable stages: per-symbol regime classify → category sub-scores → composite → macro multiply → rank. Keep `CompositeScorer` and `SymbolRanker` as separate injectable units.
- **Signal modules are stubs** (`analysis/signals/{technical,fundamental,macro,sentiment}/`) with a common `Indicator` base returning a normalized 0–100 (or signed delta) per symbol/date; the scorer consumes whatever is present (§3.3 renormalization).
- **Config is the contract:** every weight/threshold in §3 and §4 is a `config/strategy.yaml` key. Define a typed config schema (pydantic) the engine validates at startup.
- **BrokerAdapter is untouched by all of this** — scoring produces ranked candidates; `PortfolioManager` (not the scorer) calls `BrokerAdapter`. Keep the seam clean.

### Database Optimizer (Phase 1)
- **New tables (11):** `fundamentals_quarterly`, `earnings_calendar`, `earnings_estimates`, `analyst_estimates`, `insider_transactions`, `sec_filings`, `news_sentiment`, `market_sentiment`, `short_interest`, `macro_series`, `signal_values`. Intermarket ETFs **reuse `market_bars`** — no new table.
- **Hypertables:** `market_bars` (partition on `ts`, primary key `(symbol, ts)`) and `macro_series` (partition on `ts`, PK `(series_id, ts)`) and `signal_values` (PK `(symbol, ts, signal_id)`). Event tables (`insider_transactions`, `sec_filings`) are low-volume — hypertable optional.
- **Volumes are tiny:** `market_bars` ≈ 16.6k rows/yr (66 tickers); `macro_series` <1 MB for years; everything else event-driven or market-wide singletons. **Compression only matters on `market_bars` over multi-year history.** Continuous aggregates useful for NAV/rolling-return rollups, not required Phase 1.
- **Idempotent upserts everywhere** (CLAUDE.md: jobs run twice must not duplicate). Natural keys: bars `(symbol, ts)`, filings `(accession_no)`, insider `(accession_no, txn_seq)`, macro `(series_id, ts)`.
- ⚠️ **Point-in-time / revision hazard:** FRED series (CPI, NFP, LEI) AND yfinance fundamentals are *restated*. Store a `release_ts` / `as_of` column where it exists so the Experiment Tracker can avoid look-ahead bias in backtests. FRED ALFRED vintages are a Phase-2 upgrade.

### Data Engineer (Phase 4)
- **Providers to build, by priority:** (1) yfinance OHLCV — Tier 1 backbone, idempotent upsert to `market_bars`; (2) FRED macro — 13 series; (3) yfinance fundamentals + earnings dates; then Tier 2: (4) Finnhub (news sentiment + consensus EPS + recommendations); (5) SEC EDGAR (Form 4 + 8-K, UA header `name email`, 10 req/sec); (6) CBOE put/call CSV; (7) FINRA short-interest bulk.
- **Freshness / latency per source** (drives job timing — see Workflow Architect): news & CBOE & VIX = T-1 available by early UTC; 8-K within 4 business days (scan last 5); Form 4 within 2 business days (scan last 3); FINRA short interest bi-monthly (refresh on publish days, cache between); macro on each series' own release cadence.
- **Twelve Data stays as the OHLCV fallback** behind the same Protocol (CLAUDE.md). Finnhub is additive, not a yfinance replacement.
- **Pre-scored sentiment only — no on-Pi transformer.** Aggregate Finnhub per-article scores with pandas means/z-scores; 8-K text uses lightweight keyword polarity, not NLP models.
- **Rate-limit discipline:** Alpha Vantage NEWS_SENTIMENT is 25 req/day → market-wide pull only, never per-symbol. Finnhub 60/min covers 50 symbols comfortably. EDGAR needs the UA header or it 403s.

### AI Engineer (Phase 4)
- **Implementation order = Tier 1 first:** blended momentum → per-symbol regime classifier → ATR sizing inputs → earnings/revenue acceleration → quality composite → trend gate. Get a working composite on Tier-1-only signals before wiring Tier 2.
- **Scoring architecture is §3:** rank-normalize each raw signal cross-sectionally, weighted category sub-scores, bounded sentiment overlay + additive event tags, then the §4 macro multiplier × rotation tilt × calendar size factor. Implement `data_completeness` renormalization (§3.3) from day one — it's not optional.
- **Two regime layers compose per §4.3:** macro multiplies + sets profile bias; per-symbol classifier only selects the technical weight-profile. Never both multiply.
- **Everything is a config stub:** initial weights in §3.2 / §4 are defaults to hand to the Experiment Tracker for calibration — do NOT hardcode, do NOT tune by hand.
- **PEAD ownership:** the fundamental SUE computation writes the standardized surprise; the news/event PEAD tag reads it and applies the decaying bonus (gated by day-1 reaction sign). One value, two consumers.

### Workflow Architect (Phase 1)
- **The daily job sequence broadly holds** but expand the ingestion fan-out: `fetch_macro_data` (FRED) → `fetch_news_sentiment` (Finnhub + CBOE + 8-K/Form-4 EDGAR scan) → `fetch_market_data` (OHLCV: watchlist + ~16 intermarket tickers) → `fetch_fundamentals` (quarterly statements + earnings dates + short interest on publish days) → `run_analysis` (reads all from DB, never calls APIs) → `execute_paper_trades` → `update_portfolio_nav`.
- **New failure modes to design recovery for:** yfinance rate-limit/empty-frame (fallback to Twelve Data); EDGAR 403 (missing UA header); Finnhub quota exhaustion (degrade to RSS, mark sentiment missing → §3.3 renormalizes); FINRA file not yet published (use cached short interest); FRED series unrevised/stale (use last value); a single provider failing must **not** abort `run_analysis` — it scores on available data and records `data_completeness`.
- **Idempotency is mandatory** (jobs may rerun within `misfire_grace_time=3600`): all upserts keyed on natural keys; PEAD/event tags must be recomputed deterministically, not appended.
- **Cadence mismatches:** most signals are daily, but short interest is bi-monthly, 13F quarterly, FINRA dark-pool weekly — the scheduler needs per-source refresh gating, not a blind daily fetch of everything.
- **Calendar gating:** earnings de-risk windows, FOMC days, and Triple-Witching are pure date math computed in `run_analysis` / `execute_paper_trades` to scale position sizing — no fetch, but the workflow must apply them before order generation.

---

## Handoff notes

**What this document produced:** the master signal priority matrix (31 signals across three tiers), a Tier-1/Tier-2 data-source map with DB-sizing estimates, the complete composite-scoring architecture (pipeline, stub weights, missing-data renormalization, anti-domination rules), the three-state macro regime spec with the two-layer composition rule resolved, the final 50-symbol watchlist with role/coverage annotations, and per-agent handoff briefs.

**Decisions resolved (the open questions from all three Phase-0A streams):**
- Primary horizon = **1–4 weeks**, technical-led (w_tech 0.60 / w_fund 0.40 stub).
- **alternative.me dropped** (crypto-only); equity Fear & Greed rebuilt from owned components.
- **PEAD single ownership:** fundamental computes SUE, news/event consumes it.
- **Two regime layers compose** (macro multiplies + biases; per-symbol selects profile) — no double-count.
- **Breadth = ETF proxy** (RSP/SPY, IWM/SPY); no 500-component scans in Phase 1.
- **PMI proxy = MANEMP + OECD CLI** accepted for Phase 1; real ISM is Phase 2.
- **Provider stack:** yfinance + FRED (Tier 1) + Finnhub + SEC EDGAR + CBOE + FINRA (Tier 2). Finnhub free tier unblocks SUE/revisions. No paid sources Phase 1.
- Decayed seasonals ship as **0.0 config defaults** for the Experiment Tracker to test.

**Agents cleared to proceed to Phase 1 (parallel):**
- ✅ **Software Architect** — protocols, module structure, config schema (§6).
- ✅ **Database Optimizer** — 11 new tables + hypertable plan + point-in-time concern (§2, §6).
- ✅ **Workflow Architect** — expanded job fan-out, new failure modes, cadence gating (§6).

Phase 2 (Financial Analyst metrics, FP&A, Experiment Tracker) and beyond consume this document but depend on Phase 1 contracts first. **Phase 1 may now begin.**
