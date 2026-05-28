<!-- Agent: Investment Researcher | Phase: 0A | Depends on: CLAUDE.md -->

# Phase 0A — Technical & Fundamental Signals Research

**Stream:** Technical price signals + company fundamental signals
**Goal:** Identify signals with genuine *predictive* (forward-looking) edge that can be computed daily from free data (`yfinance` + `ta`), to feed a multi-factor composite scorer.

> Scope note: This is a paper-trading research system on a Raspberry Pi 4. Every recommendation below is filtered through three constraints: (1) computable from free daily data, (2) cheap enough to run on ARM64/4GB, (3) backed by published academic evidence rather than chart-pattern folklore. Signals with no out-of-sample evidence are explicitly flagged "avoid."

---

## SECTION 1 — Sector Universe

### Evaluation framework

Each sector is rated on four axes relevant to *daily-frequency prediction*:

- **Predictability** — does the published cross-section of returns respond to technical/fundamental factors here? (momentum and PEAD are stronger in some sectors)
- **Liquidity** — clean fill assumption needs liquid names; we set a floor of **$20M average daily dollar volume** for individual stocks (ETFs far exceed this).
- **Volatility (ATR%)** — ATR as % of price. Higher = more signal amplitude but more risk and more whipsaw. Sweet spot for daily signals is roughly **1.5%–4%** ATR%.
- **Correlation / diversification** — how much it co-moves with SPY (for portfolio construction).

### Sector recommendation matrix

| Sector | Predictability | Liquidity | Typical ATR% | SPY corr | Structural quirks | Verdict |
|---|---|---|---|---|---|---|
| **Technology** | High (strong momentum + PEAD) | Excellent | 2–4% | High (~0.85) | Earnings clustered late Jan/Apr/Jul/Oct; mega-cap concentration distorts cap-weighted ETFs | **Prioritize** |
| **Communication Services** | High (momentum) | Excellent | 2–4% | High (~0.8) | Dominated by GOOGL/META/NFLX — really "tech-adjacent"; narrow breadth | **Prioritize** |
| **Consumer Discretionary** | High (momentum, sentiment-sensitive) | Excellent | 2–4% | High (~0.85) | AMZN/TSLA dominate XLY; cyclical, macro-sensitive | **Prioritize** |
| **Financials** | Medium-High (value + macro/rate sensitivity) | Excellent | 1.5–3% | Medium-High (~0.75) | Rate-curve driven; P/B works well here; earnings concentrated | **Prioritize (value tilt)** |
| **Healthcare** | Medium (binary biotech events hurt predictability) | Good (large caps), poor (small biotech) | 1.5–6% | Medium (~0.65) | FDA/trial catalysts = gap risk; split mega-pharma (predictable) vs biotech (gambling) | **Selective** |
| **Industrials** | Medium (value + quality, cyclical) | Good | 1.5–3% | Medium-High (~0.8) | Cyclical; sensitive to PMI/ISM macro | **Include** |
| **Energy** | Medium (commodity-driven, momentum exists) | Good | 2.5–5% | Low-Medium (~0.5) | Driven by crude, not company fundamentals; great diversifier, noisy | **Include (diversifier)** |
| **Materials** | Medium (commodity + cyclical) | Good | 2–4% | Medium (~0.7) | Commodity-linked; smaller sector | **Include** |
| **Consumer Staples** | Low-Medium (defensive, slow) | Good | 1–2% | Low (~0.55) | Low vol = low signal amplitude; mean-reverting, defensive | **Defensive sleeve only** |
| **Utilities** | Low (rate-proxy, low vol) | Good | 1–2% | Low (~0.4) | Behaves like a bond proxy; little technical edge | **Defensive sleeve only** |
| **Real Estate (REITs)** | Low-Medium (rate-driven) | Good | 1.5–3% | Medium (~0.6) | Highly rate-sensitive; FFO ≠ EPS so standard fundamentals mislead | **Caution** |

### ETF universe verdict

| Type | Examples | Role | Verdict |
|---|---|---|---|
| Broad index | SPY, QQQ, IWM, DIA | Regime/benchmark + relative-strength denominator | **Core** |
| Sector SPDRs | XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC | Sector rotation + relative strength base | **Core** |
| Factor ETFs | MTUM (momentum), VLUE (value), QUAL (quality), USMV (low-vol), VTV/VUG | Factor regime read + low-noise momentum exposure | **Include** |
| Volatility proxy | ^VIX (index), VIXY (tradeable) | Regime filter only (not a position) | **Signal input** |

### Recommendation summary

- **Prioritize for prediction:** Technology, Communication Services, Consumer Discretionary, Financials. These carry the strongest momentum + PEAD + value signal density and are deeply liquid.
- **Include with care:** Industrials, Energy, Materials, Healthcare large-caps. Good diversifiers; energy decouples from SPY (portfolio value).
- **Avoid as alpha source / use defensively:** Utilities, Staples, REITs. Low ATR% means little daily signal; keep them as a *defensive sleeve* the macro regime can rotate into, not as signal generators.
- **Avoid:** small-cap biotech, illiquid micro-caps (gap/event risk destroys daily prediction and clean-fill assumptions).

---

## SECTION 2 — Technical Signals (what actually predicts price)

> Convention below: **Horizon** = the holding period the edge is documented on. **Type** = Leading (predictive) vs Lagging (confirmation/filter). Daily bars assumed; all computable in `ta`/pandas.

### 2.1 PRICE MOMENTUM — strongest documented technical edge

**Why it works (behavioral):** Investor *underreaction* to information (gradual diffusion of news) plus *delayed overreaction*/herding. The cross-sectional momentum premium (Jegadeesh & Titman 1993) is one of the most robust anomalies, surviving out-of-sample across markets and decades.

| Signal | Parameters with backing | Horizon | Type | Notes |
|---|---|---|---|---|
| **12–1 momentum** | Cumulative return over months t-12 to t-2, **skip the most recent month** | 1–6 months | Leading | The flagship. Skipping the last month removes 1-month short-term *reversal* (microstructure/liquidity reversal) that contaminates raw 12m return. |
| **ROC lookbacks** | 3m, 6m, 12m show edge; **1m is reversal, not momentum** | 1–3 months | Leading | 6m and 12m are the workhorses. Blend (avg of 3/6/12m rank) is more stable than any single. |
| **Relative strength vs SPY & sector** | Rolling 60d / 120d return of symbol minus benchmark | 1–3 months | Leading | Dual RS (beats both SPY *and* its sector ETF) is a strong filter — isolates idiosyncratic strength from beta. |
| **52-week high proximity** | Price within ~0–5% of 252d high | 1–6 months | Leading | George & Hwang (2004): nearness-to-52w-high predicts returns *better than past-return momentum* — anchoring bias means investors under-buy at new highs. |

**Recommendation:** Make a **blended momentum rank** (3/6/12m ROC + 52w-high proximity + dual relative strength) the single highest-weight technical input. Always implement the 1-month skip.

### 2.2 TREND SIGNALS — mostly filters, weak standalone alpha

**Why:** Trend-following on single stocks at daily frequency is largely *lagging*. Useful as a **regime filter / gate**, weak as a primary predictor.

| Signal | Backing | Horizon | Type | Verdict |
|---|---|---|---|---|
| **MA crossovers** | 50/200 ("golden/death cross") has weak, late edge; faster pairs (10/20) = noise on single names | weeks–months | Lagging | Use 50/200 only as a coarse **trend gate**, not a trigger. |
| **MA slope** | Slope (ROC of the MA) of 50d/100d as up/down/flat | weeks | Lagging | Better than crossover: a rising 50d slope is a cleaner "is this in an uptrend" boolean. **Use as gate.** |
| **Price vs MA distance** | (Price − MA)/ATR; extreme distance = stretched | days–weeks | Leading (reversion) | Distance normalized by ATR is a useful *mean-reversion* input (overextension), not a trend input. |

**Recommendation:** Use **200d MA position + 50d slope** as a binary trend regime gate. Use **price-to-MA distance in ATR units** as a mean-reversion overextension signal. Do not trade MA crossovers as signals.

### 2.3 MOMENTUM OSCILLATORS

**Why:** Capture short-term over-extension. Predictive value is *regime-dependent* — they work for reversion in range-bound names and give false signals in strong trends.

| Signal | Recommended params | Horizon | Type | Verdict |
|---|---|---|---|---|
| **RSI** | RSI(14). For prediction use it as a **trend-aware reversion** input: in uptrends, 40 is the meaningful "oversold" floor (not 30); 30/70 are best in range regimes. RSI(2) is a known short-term mean-reversion edge (Connors) but very short-horizon. | 3–15 days | Leading (reversion) | Use **regime-conditioned RSI(14)**; consider RSI(2) as a short-term reversion overlay. |
| **MACD** | (12,26,9). **Histogram** (momentum of momentum) leads the signal-line cross. | 1–3 weeks | Lagging-ish | Histogram *direction change* > signal cross. Use as confirmation, low weight. |
| **Stochastic** | (14,3,3) | days | Leading but noisy | Too noisy on daily single-stock bars. **Avoid** as standalone; redundant with RSI. |

**Recommendation:** RSI(14) regime-conditioned is the keeper oscillator. MACD histogram as a minor confirmation. Drop Stochastic (redundant + noisy).

### 2.4 VOLUME SIGNALS

**Why:** Volume reveals conviction / institutional participation that price alone hides. Price moves on rising volume are more likely to persist.

| Signal | Definition | Horizon | Type | Verdict |
|---|---|---|---|---|
| **OBV** | Cumulative signed volume; **OBV making new highs before price** = accumulation | 1–4 weeks | Leading | Useful divergence detector (OBV up, price flat = stealth accumulation). Keep. |
| **Volume surge** | Volume ≥ **2× (caution) / 3× (strong)** of 20d avg | 1–10 days | Leading (confirmation) | A breakout on ≥2× volume is far more reliable than on average volume. Strong confirmation gate. |
| **Price–volume divergence** | Price up on declining volume = weak rally | 1–3 weeks | Leading (warning) | Good *exit/avoid* signal; weaker as entry. |
| **VWAP** | Anchored VWAP useful, but **rolling daily VWAP needs intraday data** | intraday | n/a | **Avoid at daily frequency** — VWAP needs intraday bars we don't ingest. |

**Recommendation:** OBV divergence + volume-surge confirmation are the two volume keepers. Drop VWAP (requires intraday data we don't have).

### 2.5 VOLATILITY SIGNALS

**Why:** Volatility is mean-reverting and *regime-defining*. Low-vol "squeezes" precede expansions; ATR sizes risk.

| Signal | Use | Horizon | Type | Verdict |
|---|---|---|---|---|
| **ATR (14)** | Position sizing (risk parity), stop placement, breakout confirmation (close > N×ATR move) | n/a | n/a | **Essential** — primary input to `risk_manager` position sizing. |
| **Bollinger Band width** | BB width percentile; **squeeze** (width in bottom decile) precedes expansion | 1–4 weeks | Leading | The squeeze is a genuine "big move coming (direction TBD)" pre-signal. Pair with momentum/breakout for direction. Keep. |
| **Historical volatility** | 20d realized vol as a **filter** — exclude near-dead low-vol names; cap exposure on extreme-vol names | n/a | Filter | Keep as a universe filter (ties back to Section 1 ATR% sweet spot). |

**Recommendation:** ATR for sizing (mandatory), BB-width squeeze as a pre-breakout pre-signal, realized vol as a tradability filter.

### 2.6 MEAN REVERSION vs MOMENTUM — regime detection

The single most important meta-decision: *the same indicator means opposite things in different regimes.*

- **Momentum dominates** in: trending markets, higher-beta growth sectors (Tech, Comm Services, Discretionary), longer horizons (1–6m), index uptrends.
- **Mean reversion dominates** in: range-bound/choppy markets, defensive low-beta sectors (Staples, Utilities), very short horizons (1–5d), high-VIX panic spikes (oversold bounces).

**How to detect regime per symbol (all daily-computable):**
- **Hurst-ish trendiness proxy / efficiency ratio** (Kaufman): net change ÷ sum of absolute daily changes over N days. High (>~0.4) = trending → use momentum; low = choppy → use reversion.
- **ADX (14):** > 25 trending (momentum), < 20 ranging (reversion).
- **Autocorrelation of daily returns** over 60d: positive = momentum regime, negative = reversion regime.
- **Market regime gate:** SPY above/below 200d MA + VIX level → risk-on (momentum) vs risk-off (reversion/defensive).

**Recommendation:** Implement a per-symbol **regime classifier** (efficiency ratio + ADX) that switches the scorer between a momentum-weighted and reversion-weighted profile. This is the highest-leverage technical design decision and should be a first-class config in `strategy.yaml`.

---

## SECTION 3 — Fundamental Signals (company health predicts future price)

> Horizon caveat: fundamentals work on **weeks-to-quarters**, slower than technicals. They set the *which stocks* universe tilt; technicals time the *when*.

### 3.1 EARNINGS & ANALYST SIGNALS — highest academic evidence

**Why the edge exists:** Markets *underreact* to earnings news and analyst revisions; information diffuses slowly (Bernard & Thomas PEAD; analyst-revision underreaction). This is arguably the strongest, most-replicated fundamental anomaly.

| Signal | Computation | Horizon | Edge mechanism | yfinance? |
|---|---|---|---|---|
| **Earnings surprise / SUE** | (Actual EPS − Consensus EPS) ÷ stdev of past surprises (standardized). Magnitude matters, not just sign. | **PEAD: 1–3 months** post-report | Underreaction; drift in direction of surprise persists ~60 days | Partial — actual + estimate via `earnings_dates`/`get_earnings_dates`; consensus history is **thin/unreliable** ⚠️ |
| **Post-earnings drift (PEAD)** | After a beat (positive SUE), bias long for ~1–2 months; after a miss, bias away | 1–2 months | Same as above | Derivable once SUE available |
| **Earnings-revision momentum** | Count/net of analyst EPS estimate **upgrades minus downgrades** over 30/60d; or Δ mean forward EPS estimate | 1–3 months | Analysts revise in herds, slowly → trend persists | Partial — `recommendations` / estimate trends are **incomplete** ⚠️ |
| **Earnings & revenue acceleration** | 2nd derivative: YoY growth rate increasing across last 3 quarters (both rev AND EPS) | 1–2 quarters | Acceleration is under-priced vs level | Yes — quarterly `income_stmt` |
| **Guidance changes** | Management raising forward guidance = strongest fundamental signal | 1–2 quarters | Direct insider forecast | ❌ Not structured in yfinance — needs news/transcript parsing |
| **Upgrade/downgrade cascades** | Rating changes; first-mover advantage | days–weeks | Underreaction to first revision | Partial — `upgrades_downgrades` exists but coverage spotty ⚠️ |

**Recommendation:** Earnings-revision momentum + SUE/PEAD are the **top-priority fundamental signals** — but data quality from yfinance is the binding constraint (see handoff). Earnings/revenue **acceleration** is fully computable from yfinance financials and should be the reliable backbone. Treat the analyst-estimate-dependent signals as "implement behind a data-availability check."

### 3.2 VALUATION FACTORS

**Why:** The value premium (cheap mean-reverts upward) — Fama-French HML. Works slowly and is regime-dependent (value outperforms in recoveries/high-rate regimes).

| Signal | Computation | Horizon | Best in sectors | yfinance? |
|---|---|---|---|---|
| **P/E relative to sector** | Symbol trailing P/E ÷ sector median P/E (z-score within sector) | months–quarters | Cross-sector comparison only | Yes (`info`/`fast_info`) — but use **relative**, never absolute |
| **PEG (P/E ÷ growth)** | Forward P/E ÷ expected EPS growth; **PEG < 1** as a cheap-growth filter | quarters | Growth sectors (Tech) | Partial — needs growth estimate ⚠️ |
| **Price-to-Book** | Price ÷ book value/share | quarters | **Financials, Industrials, Materials** (asset-heavy); meaningless for asset-light Tech | Yes |
| **EV/EBITDA** | Enterprise value ÷ EBITDA; capital-structure-neutral | quarters | Capital-intensive (Energy, Industrials, Telecom) — more reliable than P/E | Yes (EV + EBITDA in `info`/financials) |
| **Forward vs trailing P/E divergence** | Forward P/E ≪ trailing P/E ⇒ market expects EPS growth | months | All | Partial — forward P/E availability varies ⚠️ |

**Recommendation:** Always compute valuation **sector-relative** (z-score within GICS sector) — absolute multiples are noise across sectors. P/B for asset-heavy sectors, EV/EBITDA for capital-intensive, sector-relative P/E elsewhere. Treat valuation as a **tilt/tiebreaker**, lower weight than momentum/earnings for a daily system.

### 3.3 QUALITY FACTORS

**Why:** The quality premium (Novy-Marx gross profitability; Asness "Quality Minus Junk"). Profitable, low-leverage, improving-margin firms outperform — the market under-prices durable quality.

| Signal | Computation | Horizon | Edge | yfinance? |
|---|---|---|---|---|
| **ROE + ROE trend** | Net income ÷ equity; trend over 4 quarters | quarters | Persistent-ROE firms outperform | Yes |
| **Gross margin expansion** | Δ gross margin QoQ/YoY; rising before market prices it | 1–2 quarters | Margin trend leads earnings | Yes (`income_stmt`) |
| **Revenue growth acceleration** | 3 consecutive quarters of increasing YoY revenue growth | 1–2 quarters | Under-priced acceleration | Yes |
| **FCF yield** | Free cash flow ÷ market cap; high = value+quality combo | quarters | Hard to manipulate vs EPS | Yes (`cashflow`) — **most robust** quality metric in yfinance |
| **Debt/equity trend** | Total debt ÷ equity; firms *de-levering* outperform | quarters | Lower financial risk | Yes (`balance_sheet`) |
| **Operating leverage** | Revenue growth rate > opex growth rate ⇒ margin expansion coming | 1–2 quarters | Leading margin signal | Yes (derive from income_stmt) |

**Recommendation:** **FCF yield + gross-margin trend + ROE trend** form a clean, fully-yfinance-computable quality composite. Quality pairs best as a *filter on momentum* ("quality momentum" — high momentum AND improving fundamentals greatly outperforms momentum alone and reduces crashes).

### 3.4 INSIDER ACTIVITY — strong, under-watched leading indicator

**Why:** Insiders have the best information about their own firm; **insider *buying*** (Form 4 open-market purchases) is a documented bullish predictor (Lakonishok & Lee; Cohen, Malloy & Pomorski on "opportunistic" insiders). Selling is noisy (diversification/liquidity), buying is informative.

| Signal | Computation | Horizon | Edge | Source |
|---|---|---|---|---|
| **Form 4 open-market buys** | Insider purchases (transaction code **P**), exclude option exercises | **1–6 months** | Strongest insider signal | SEC EDGAR / OpenInsider |
| **Buy/sell ratio** | # buying insiders ÷ total transacting, 90d window | 1–6 months | Conviction breadth | OpenInsider |
| **Cluster buying** | ≥3 insiders buying within 30 days | 1–6 months | Strongest variant — multiple informed agents agree | OpenInsider / EDGAR |
| **Role weighting** | CEO/CFO buys > director buys | 1–6 months | Higher information content | EDGAR Form 4 |

**Data:** ❌ **Not in yfinance.** Requires OpenInsider.com scraping (free, structured HTML) or SEC EDGAR full-text Form 4 API (free, robust, but XML parsing). EDGAR is the durable choice; OpenInsider is faster to prototype. Both fit the `data_ingestion/providers/` Protocol pattern. **Defer to Phase 4** behind the provider seam; high value, medium build cost.

---

## SECTION 4 — Watchlist Seed (initial universe)

> Populate the `watchlist` table at runtime from this seed (CLAUDE.md forbids hardcoding in code — this list lives in config/seed data, not source). Tiers: Mega ≥ $200B, Large $10–200B, Mid $2–10B. Asset = Stock/ETF.

### Broad index & regime ETFs

| Ticker | Name | Sector | Asset | Tier | Primary use |
|---|---|---|---|---|---|
| SPY | SPDR S&P 500 | Broad | ETF | — | Benchmark / RS denominator / regime |
| QQQ | Invesco Nasdaq 100 | Broad/Tech | ETF | — | Growth regime |
| IWM | iShares Russell 2000 | Broad/Small | ETF | — | Risk-on breadth |
| DIA | SPDR Dow 30 | Broad | ETF | — | Value/large benchmark |
| VIXY | ProShares VIX Short-Term | Volatility | ETF | — | Regime fear gauge |

### Sector SPDR ETFs (relative-strength / rotation base)

| Ticker | Sector |
|---|---|
| XLK | Technology |
| XLC | Communication Services |
| XLY | Consumer Discretionary |
| XLF | Financials |
| XLV | Healthcare |
| XLI | Industrials |
| XLE | Energy |
| XLB | Materials |
| XLP | Consumer Staples |
| XLU | Utilities |
| XLRE | Real Estate |

### Factor ETFs

| Ticker | Factor |
|---|---|
| MTUM | Momentum |
| VLUE | Value |
| QUAL | Quality |
| USMV | Min Volatility |
| VUG | Growth |

### Single stocks (anchors + signal test beds)

| Ticker | Name | Sector | Tier | Primary signal use |
|---|---|---|---|---|
| AAPL | Apple | Technology | Mega | Momentum + quality + PEAD anchor |
| MSFT | Microsoft | Technology | Mega | Quality/FCF + momentum |
| NVDA | NVIDIA | Technology | Mega | High-ATR momentum + earnings acceleration |
| AVGO | Broadcom | Technology | Mega | Momentum + FCF yield |
| AMD | Adv. Micro Devices | Technology | Large | High-vol momentum, PEAD |
| CRM | Salesforce | Technology | Large | Margin expansion / quality |
| ADBE | Adobe | Technology | Large | FCF quality + revision momentum |
| GOOGL | Alphabet | Comm Services | Mega | Momentum + valuation |
| META | Meta Platforms | Comm Services | Mega | Momentum + margin trend |
| NFLX | Netflix | Comm Services | Large | Momentum + PEAD |
| AMZN | Amazon | Cons. Disc. | Mega | Momentum + operating leverage |
| TSLA | Tesla | Cons. Disc. | Mega | Extreme-ATR momentum + sentiment test |
| HD | Home Depot | Cons. Disc. | Large | Cyclical + dividend quality |
| MCD | McDonald's | Cons. Disc. | Large | Defensive-cyclical, low-vol |
| NKE | Nike | Cons. Disc. | Large | Mean-reversion / valuation test |
| JPM | JPMorgan | Financials | Mega | P/B value + rate sensitivity |
| BAC | Bank of America | Financials | Large | Value + macro/rate |
| GS | Goldman Sachs | Financials | Large | Value + earnings surprise |
| V | Visa | Financials | Mega | Quality/FCF compounder |
| BRK-B | Berkshire Hathaway | Financials | Mega | Low-vol value anchor |
| UNH | UnitedHealth | Healthcare | Mega | Large-cap quality (non-biotech) |
| LLY | Eli Lilly | Healthcare | Mega | Momentum + earnings acceleration |
| JNJ | Johnson & Johnson | Healthcare | Mega | Defensive quality |
| ABBV | AbbVie | Healthcare | Large | FCF yield + dividend |
| CAT | Caterpillar | Industrials | Large | Cyclical + PMI macro proxy |
| GE | GE Aerospace | Industrials | Large | Turnaround / revision momentum |
| HON | Honeywell | Industrials | Large | Quality cyclical |
| UNP | Union Pacific | Industrials | Large | Cyclical, EV/EBITDA |
| XOM | Exxon Mobil | Energy | Mega | Commodity momentum + FCF yield |
| CVX | Chevron | Energy | Large | Energy diversifier |
| COP | ConocoPhillips | Energy | Large | Commodity beta |
| LIN | Linde | Materials | Large | Quality industrial-materials |
| FCX | Freeport-McMoRan | Materials | Large | Commodity/cyclical high-ATR |
| NEM | Newmont | Materials | Large | Gold proxy (low SPY corr) |
| PG | Procter & Gamble | Cons. Staples | Mega | Defensive sleeve / low-vol |
| KO | Coca-Cola | Cons. Staples | Large | Defensive mean-reversion |
| COST | Costco | Cons. Staples | Mega | Quality compounder (staples-growth) |
| NEE | NextEra Energy | Utilities | Large | Defensive / rate proxy |
| DUK | Duke Energy | Utilities | Large | Defensive sleeve |
| PLD | Prologis | Real Estate | Large | REIT (rate-sensitive test) |
| AMT | American Tower | Real Estate | Large | REIT + rate sensitivity |

**Seed total:** 5 index ETFs + 11 sector ETFs + 5 factor ETFs + 41 stocks = **62 symbols** (trim to ~50 at runtime if Pi load requires). Coverage spans all 11 GICS sectors, all three cap tiers, and every signal category above has at least 3 clean test beds.

---

## Handoff notes

**What this document produced:** A sector-prioritization matrix, an evidence-ranked catalogue of technical and fundamental signals (with parameters, horizons, leading/lagging classification, and yfinance availability), a per-symbol regime-detection recommendation, and a 62-symbol watchlist seed spanning all sectors/tiers.

### Priority signal ranking (which to implement first)

1. **Blended cross-sectional momentum** (3/6/12m ROC w/ 1m skip + 52w-high proximity + dual relative strength) — strongest evidence, fully yfinance-computable. **Implement first.**
2. **Per-symbol regime classifier** (efficiency ratio + ADX + SPY/VIX gate) — meta-signal that switches momentum vs reversion weighting. Highest design leverage.
3. **Earnings/revenue acceleration + quality composite** (FCF yield, ROE trend, gross-margin trend) — reliable from yfinance financials.
4. **Volatility/risk inputs** (ATR for sizing, BB-width squeeze) — needed by `risk_manager` regardless.
5. **SUE/PEAD + revision momentum** — high value but data-quality-gated (see gaps).
6. **Insider Form 4 buying** — high value, needs a new EDGAR/OpenInsider provider; **defer to Phase 4** behind the provider seam.
7. **Sector-relative valuation** — lower-weight tilt/tiebreaker.

### Data gaps (what yfinance can't / poorly provides)

- **Consensus EPS estimate history** — thin and unreliable; SUE precision is limited. Needs a fundamentals provider (Twelve Data / Finnhub free tier) for clean estimates. ⚠️
- **Analyst revision trend (count of ups/downs over time)** — `upgrades_downgrades` exists but coverage is spotty and not point-in-time. ⚠️
- **Forward EPS / forward P/E / PEG** — availability varies by ticker; PEG cannot be reliably computed for all names. ⚠️
- **Guidance changes** — not structured anywhere free; would require NLP on news/transcripts. Out of scope Phase 1.
- **Insider Form 4** — not in yfinance at all; needs dedicated SEC EDGAR / OpenInsider provider.
- **VWAP / any intraday signal** — we ingest daily bars only; VWAP and intraday volume profiles are out.
- **Point-in-time fundamentals** — yfinance gives *current* fundamentals, not as-reported snapshots, creating look-ahead/survivorship bias risk in any historical backtest. Flag for Experiment Tracker.

### Questions for the synthesis step (00-signal-synthesis.md)

1. **Composite weighting:** momentum-dominant vs balanced multi-factor? Recommendation: momentum-weighted with quality/earnings as filters and valuation as tiebreaker — synthesis must reconcile this against the macro/sentiment/smart-money streams.
2. **Regime switching scope:** per-symbol only, or also a global market-regime overlay (from the macro stream) that scales gross exposure? Needs alignment with Financial Analyst's macro regime model.
3. **Prediction-horizon target:** technicals point to a 1–4 week sweet spot; fundamentals to 1–2 quarters. The composite must declare a primary horizon — recommend **~1–4 weeks primary** with fundamental signals acting as slow tilts. Synthesis to confirm.
4. **Data-provider decision:** accept yfinance limits on estimates/revisions, or budget a second free fundamentals provider? This determines whether SUE/revision signals ship in Phase 1 or wait.
5. **New DB tables implied by this stream:** `insider_transactions`, `analyst_estimates`/`earnings_estimates`, `fundamentals_quarterly` (income/balance/cashflow line items), plus `signal_values` to persist computed signal scores per symbol/date. Hand to Database Optimizer.
6. **Overlap with other streams:** put/call & VIX (this doc uses VIX for regime; Trend stream covers put/call) — synthesis must de-duplicate ownership so a signal isn't double-counted in the composite.
