<!-- Agent: Trend Researcher | Phase: 0A | Depends on: CLAUDE.md -->

# Phase 0A — News, Sentiment & Smart-Money Signals Research

**Stream:** Information-based edge — news/events, market sentiment, smart-money activity
**Goal:** Identify signals that move *before* price (informational asymmetry, slow diffusion, contrarian extremes, informed-trader footprints) that can be fetched once per day from free sources and fed to a multi-factor composite scorer.

> Scope note: Same three filters as the sibling technical/fundamental doc apply: (1) obtainable from free / free-tier sources, (2) cheap on ARM64/4GB, (3) backed by published evidence, not folklore. One extra filter dominates this stream: **the system is a once-daily batch job.** Many sentiment/smart-money signals only carry alpha *intraday* (unusual options flow, real-time dark-pool prints). Those are explicitly marked "intraday-only → Phase 2." Every data source is evaluated for endpoint, auth, free-tier limit, historical depth, and the Python access pattern. Where free-tier numbers were verified during this research the source is cited in the Handoff; where uncertain it is flagged.

> Convention: **Horizon** = documented holding period of the edge. **Direction** = bullish/bearish/contrarian. **Type** = Leading (predictive) vs Confirming/Filter. **Verdict** = Use / Selective / Avoid (under daily-batch + free-tier constraints).

---

## SECTION 1 — News & Event Signals

### 1.1 Corporate event impact taxonomy

> The edge is not "an event happened" — by the time we fetch headlines the initial gap is gone. The edge is in events that **diffuse slowly** (drift) or where the *initial reaction is systematically wrong* (reversal). Daily-batch can only harvest multi-day effects.

| Event | Typical initial impact | Duration / drift | Direction logic | Daily-batch usable? |
|---|---|---|---|---|
| **Earnings — surprise magnitude** | Gap on report; size scales with standardized surprise (SUE) | **Drift 1–3 months** in direction of surprise (PEAD) | Underreaction to large surprises persists | **Yes** — drift is multi-day; this is the prize event |
| **Guidance change** (raise/cut) | Often larger than the EPS print itself | 1–2 quarters | Management forward-looking signal; raises beget revisions | Selective — not structured free; needs news/transcript NLP |
| **Product launch / FDA / regulatory approval** | Sharp gap (binary for biotech) | Hours–days (mostly instant); occasional multi-day drift on ramp | Pre-priced by specialists; gap risk | Avoid as predictor (gap risk); use as **exclusion filter** around known dates |
| **M&A — target** | Target spikes to near deal price | Collapses to spread; days | Target jumps to offer; remaining move = deal-risk arb, not directional | Avoid (event already priced; arb is intraday) |
| **M&A — acquirer** | Acquirer often dips (dilution / overpayment fear) | Days–weeks, noisy | Market skepticism on price paid | Selective — modest, noisy |
| **CEO/CFO change** | Volatility spike, ambiguous sign | Weeks; "new broom" can drift up | Uncertainty premium; forced change = bearish, planned = neutral | Selective — low signal-to-noise |
| **Layoffs / restructuring** | Often **+** short term (cost cut) | **3–6 month** path: short pop, then depends on cause | Cost-cut = margin relief (bullish); but layoffs as *demand collapse* signal = bearish. Demand-driven layoffs underperform; efficiency-driven outperform | Selective — sign depends on cause; needs context |
| **Buyback authorization** | Mild + on announcement | Weeks–months drift | Signals undervaluation belief + reduces float; execution ≠ announcement | Yes — mild persistent bullish tilt |
| **Dividend initiation** | + (signals confidence/maturity) | Months | Commitment signal; attracts income holders | Yes — bullish tilt |
| **Dividend cut/suspension** | Sharp − | Weeks; can overshoot then partial recovery | Distress signal; forced-seller cascade (income funds dump) | Yes — strong bearish flag |
| **SEC investigation / fraud / litigation** | Sharp − | **Multi-month overhang** until resolution | Persistent uncertainty discount; slow bleed | Yes — bearish overhang is multi-day/week |

**Recommendation:** The two events with genuine daily-batch alpha are **earnings (PEAD)** and **distress events** (dividend cut, SEC/legal overhang, demand-driven layoffs). Treat binary catalysts (FDA, M&A target) as **risk exclusions**, not signals — flag a symbol "event-locked" around known dates so the scorer doesn't take a position into a coin-flip gap.

### 1.2 Post-event drift (PEAD & information diffusion)

**Why it exists:** Markets underreact to earnings news; prices drift in the surprise direction for weeks (Bernard & Thomas 1989). The drift is the most-replicated event anomaly and is *the* reason a daily-batch system can profit from earnings even after the gap.

| Property | Finding | Implication for us |
|---|---|---|
| **Good vs bad news pricing speed** | Bad news diffuses *slower* (short-sale constraints, reluctance to sell) → negative drift often larger/longer | Down-drift on misses is a tradable short-bias / avoid signal |
| **Which events drift** | Earnings surprises, analyst revisions, guidance → multi-day drift. M&A, splits, index adds → near-instant | Concentrate on earnings + revisions |
| **Small-cap effect** | Drift is **stronger and longer in small/illiquid, low-analyst-coverage names** (slower diffusion) | But our liquidity floor excludes micro-caps → we capture the weaker large-cap drift. Mid-caps in the watchlist are the sweet spot |
| **Magnitude dependence** | Drift scales with surprise size (SUE) and is amplified when **price gap confirms** the surprise direction | Combine SUE sign with day-1 reaction sign as a confirmation gate |

**Recommendation:** Implement **PEAD as a time-decaying event tag**: on an earnings beat with positive day-1 reaction, attach a decaying bullish bonus (~30–45 trading days) to the symbol's composite score; mirror for misses. This is the single most evidence-backed signal in this entire stream. (Overlaps with the fundamental stream's SUE — synthesis must assign single ownership; see Handoff.)

### 1.3 News sentiment scoring

**Why:** Aggregated news tone has documented short-horizon predictive value (Tetlock 2007: media pessimism predicts downward pressure then reversal). The edge is weak and decays fast, so it works best as a **secondary tilt + divergence detector**, not a primary signal.

| Construct | Definition | Horizon | Direction | Verdict |
|---|---|---|---|---|
| **Daily per-symbol sentiment** | Mean (or relevance-weighted) sentiment of headlines tagged to the symbol that day | 1–5 days | Bullish tone → mild + ; extreme pessimism → contrarian + | Selective — use pre-scored API, don't build NLP on-Pi |
| **Sentiment momentum** | 3-day rolling mean sentiment vs 14-day baseline (z-score) | 3–10 days | Rising tone ahead of price = leading | **Use** — the most useful news construct |
| **Sentiment divergence** | Negative news flow **but price holds/rises** = relative strength (sellers exhausted / news priced) | 1–4 weeks | Bullish (hidden strength) | **Use** — high-quality, contrarian, evidence-aligned |
| **News volume spike** | Article count ≫ trailing average regardless of tone | days | Attention/volatility precursor, direction ambiguous | Selective — pair with price for direction |

**Build note:** Do **not** run a transformer sentiment model on the Pi. Use a **pre-scored** sentiment API (Alpha Vantage or Finnhub provide per-article sentiment) and aggregate with simple pandas means/z-scores. This respects the 4GB / ARM64 budget.

### 1.4 News data-source evaluation

| Source | Endpoint | Auth | Free-tier limit | Historical depth | Pre-scored sentiment? | Python access |
|---|---|---|---|---|---|---|
| **Alpha Vantage NEWS_SENTIMENT** | `query?function=NEWS_SENTIMENT&tickers=AAPL` | API key (free) | **~25 req/day** (severe) verified May 2026 | Limited lookback per call (time_from param) | **Yes** — per-article `overall_sentiment_score` + per-ticker relevance & sentiment | `requests.get`; key in env |
| **Finnhub company-news** | `/api/v1/company-news?symbol=AAPL&from=&to=` | API key (free) | **60 calls/min** free; news + basic fundamentals + SEC filings included | ~1 year on company-news | Partial — `/news-sentiment` endpoint exists but coverage/limits vary | `requests` or `finnhub-python` |
| **NewsAPI.org** | `/v2/everything?q=` | API key (free) | **100 req/day, dev-only, articles delayed**, non-production per ToS | ~1 month on free | **No** sentiment; raw articles only | `requests` or `newsapi-python` |
| **SEC EDGAR Full-Text Search (EFTS)** | `https://efts.sec.gov/LATEST/search-index?q=&forms=8-K` | None (User-Agent header required) | **10 req/sec fair-access**; no daily cap | Full archive (2001+) | No — raw filing text | `requests` with `User-Agent: name email` |
| **Financial-media RSS** (Yahoo Finance, SEC, Nasdaq, MarketWatch, Seeking Alpha public feeds) | per-feed RSS URLs | None | Unlimited (polite polling) | Only current window | No | `feedparser` |

**Verdict on news sources:**
- **Finnhub is the primary news provider** — 60 calls/min easily covers a ~50-symbol daily batch, includes company news and SEC filings, free. **Use.**
- **Alpha Vantage NEWS_SENTIMENT** has the best *pre-scored* sentiment but **25 req/day kills per-symbol coverage** for 50 names. Use only as a low-frequency *market-wide* sentiment pull (e.g., one broad-topic call/day), not per-symbol. **Selective.**
- **NewsAPI.org**: dev-only + delayed + no sentiment + paid jump to $449/mo → **Avoid** for this project.
- **SEC EDGAR EFTS**: free, unlimited-ish, authoritative → **Use** for 8-K event detection (Section 3.5).
- **RSS**: free unlimited fallback for headline volume/attention; no sentiment → **Selective** backup.

---

## SECTION 2 — Market Sentiment Signals

> These are mostly **market-wide regime / contrarian** signals (one value per day for the whole market), not per-symbol. They feed a global risk-on/risk-off overlay rather than the cross-sectional ranking. Daily-batch friendly because they are daily series.

### 2.1 Fear & Greed / volatility sentiment

| Signal | What it predicts | Horizon | Direction | Evidence | Verdict |
|---|---|---|---|---|---|
| **VIX absolute level** | Forward returns after extreme fear | days–weeks | **Contrarian**: VIX spikes (>30–40) historically precede rebounds; sustained low VIX (<13) = complacency, modestly worse fwd risk-adjusted returns | Strong (well-documented mean reversion of vol) | **Use** as regime input (already used by technical stream for regime gate — de-dupe) |
| **VIX term structure** (VIX9D / VIX / VIX3M) | Stress vs calm regime | days | **Backwardation** (short > long, ratio >1) = acute fear → contrarian bounce setup; steep contango = complacency | Moderate–strong | **Use** — `^VIX9D`,`^VIX`,`^VIX3M`,`^VXV` via yfinance; compute ratio daily |
| **CNN Fear & Greed Index** | Aggregate of 7 sentiment sub-indicators | days–weeks | **Contrarian** at extremes (<20 extreme fear = buy bias; >80 extreme greed = caution) | Moderate (composite of known signals) | **Selective** — no official API; undocumented JSON endpoint exists (fragile) |
| **AAII Sentiment Survey** (bull/bear %) | Retail investor positioning | 1–4 weeks | **Contrarian** at extremes (bull-bear spread very high = caution; very low = bounce) | Moderate | Selective — weekly (Thu), scrape; weekly cadence is fine for batch |

**Note on data:** **Alternative.me's Fear & Greed index is CRYPTO-ONLY** (Bitcoin sentiment), not equities — do **not** use it as a stock-market gauge despite CLAUDE.md's data-source table listing it. The equity equivalent is **CNN's** index, which has no official API (only an undocumented endpoint). Recommendation: **build the F&G concept from components we already fetch** (VIX, put/call, breadth, momentum) rather than depend on a fragile scrape. This is a correction to flag in synthesis.

### 2.2 Options sentiment

| Signal | Definition | Horizon | Direction | Verdict (daily-batch) |
|---|---|---|---|---|
| **CBOE total put/call ratio** | Total puts ÷ calls volume | days–weeks | **Contrarian**: very high P/C (>~1.1) = excess fear → bullish; very low (<~0.7) = greed | **Use** — daily series, market-wide regime input |
| **Equity-only put/call** | Excludes index hedging | days | Cleaner retail-fear gauge than total | **Use** if obtainable |
| **IV vs HV premium** | Implied vol − realized vol | days–weeks | High premium = fear priced in; collapse = complacency | Selective — needs per-symbol option chain |
| **Skew (put IV − call IV)** | 25-delta put vs call IV | days | Rising skew = downside hedging demand (bearish positioning / contrarian) | **Avoid daily** — per-symbol full chain pull is heavy on Pi; intraday-sensitive |

**Data:** CBOE publishes historical P/C ratios (daily CSV, free). VIX and term-structure indices via **yfinance** (`^VIX`, `^VIX9D`, `^VIX3M`/`^VXV`). Per-symbol skew/IV requires `Ticker.option_chain()` (yfinance) which is **end-of-day snapshot only, slow, and rate-limited** — feasible for a handful of names but not the whole watchlist daily.

**Verdict:** Market-wide **put/call + VIX term structure** are the keeper options-sentiment signals (cheap, daily, contrarian-validated). Per-symbol skew/IV → **Phase 2** (needs richer option data).

### 2.3 Retail sentiment (alternative data)

| Signal | Definition | Horizon | Direction | Verdict |
|---|---|---|---|---|
| **Reddit WSB mention frequency** | Daily count + Δ of symbol mentions | 1–5 days | Spike = retail attention; **mixed**: momentum short-term, mean-reversion / fade after blow-off | Selective — attention proxy, not directional alone |
| **StockTwits volume & sentiment** | Message volume + bullish/bearish tags | 1–5 days | Attention + crowd tone; extreme bullishness = contrarian | Selective — API access tightened; check current terms |
| **Google Trends search interest** | Relative search volume for ticker/company | days–weeks | Rising retail attention precedes retail-driven moves; extreme = blow-off risk | **Selective** — `pytrends` (unofficial), rate-limited/fragile, weekly granularity for long windows |

**Evidence:** Retail attention (search/social) predicts short-term **volume and volatility** more reliably than *direction*. Useful as an **attention/risk flag** and contrarian extreme detector, weak as a standalone directional alpha. **Avoid as a primary signal**; include as a low-weight attention overlay if the scrapers prove stable on-Pi.

### 2.4 Short interest

| Signal | Definition | Horizon | Direction | Verdict |
|---|---|---|---|---|
| **Short % of float** | Shares short ÷ float | weeks | High level alone ≈ weak/ambiguous | Selective — level is noisy |
| **Short-interest trend** | Δ short interest period-over-period | weeks | **Rising** = growing bearish conviction (bearish); **falling/covering** = bullish | **Use** — trend > level (better evidence) |
| **Days-to-cover (short ratio)** | Shares short ÷ avg daily volume | weeks | High DTC (>~5–7) + bullish catalyst = squeeze fuel | Selective — squeeze trigger, not standalone |

**Data:** **FINRA** publishes consolidated short interest **twice monthly**, free, as pipe-delimited bulk files; data is as-of the settlement date and **published on the 7th business day after settlement** (verified May 2026) — so expect a multi-day lag. `yfinance` exposes `shortPercentOfFloat` / `sharesShort` in `.info` (convenient but point-in-time current value, no clean history).

**Verdict:** **Use short-interest *trend* + days-to-cover** as a low-frequency (bi-monthly refresh) bearish-conviction / squeeze input. Lag is acceptable because the signal horizon is weeks. Pull via yfinance for convenience, FINRA bulk file for accuracy/history.

---

## SECTION 3 — Smart Money Signals

> "Smart money" = informed traders whose footprints leak before price fully adjusts. Free + daily-batch-viable footprints are **insider Form 4 buying** (strong) and **8-K material-event detection** (timely). Real-time options flow and dark-pool prints are intraday signals → Phase 2.

### 3.1 Insider trading (Form 4) — strongest free smart-money alpha

**Why validated:** Insiders trade on superior knowledge of their own firm. **Open-market buying** predicts positive abnormal returns (Lakonishok & Lee 2001; Jeng/Metrick/Zeckhauser). Cohen, Malloy & Pomorski (2012) show *"opportunistic"* insiders (non-routine traders) carry the real signal. Selling is mostly noise (diversification, taxes, option-funded liquidity); **buying is informative.**

| Signal | Definition | Horizon | Direction | Strength |
|---|---|---|---|---|
| **Open-market purchase (code P)** | Form 4 transaction code **P**, exclude option exercises (M) and grants (A) | **1–6 months** | Bullish | **Strongest** free insider signal |
| **Cluster buying** | ≥3 distinct insiders buying within ~30 days | 1–6 months | Bullish (multiple informed agents agree) | **Strongest variant** |
| **Insider rank weighting** | CEO/CFO buys > other officers > directors | 1–6 months | Bullish, weighted by role | High info content |
| **Buy/sell breadth ratio** | # buying insiders ÷ # transacting, 90d | 1–6 months | Bullish if >0.5 | Moderate–high |
| **Open-market sales** | Code S | n/a | Mostly noise | **Avoid as bearish** (false signals) |

**When the move materializes:** Form 4 must be filed **within 2 business days** of the transaction. Drift accrues over the *following weeks-to-months*, so daily-batch capture is fine — we are not late by acting on the filing day.

**Data sources:**
| Source | Endpoint | Auth | Limit | Format | Python |
|---|---|---|---|---|---|
| **SEC EDGAR Form 4** | submissions API + filing index; `data.sec.gov/submissions/CIK##########.json` then fetch Form 4 XML | None (UA header) | 10 req/sec | XML (`<transactionCode>`) | `requests` + XML parse |
| **OpenInsider** | `openinsider.com` screener result tables | None | Polite scrape | HTML tables | `requests` + `pandas.read_html` |

**Verdict:** **Use — top smart-money priority.** OpenInsider is fastest to prototype (pre-parsed, has cluster screens); SEC EDGAR is the durable, ToS-clean source (XML parsing cost). Build behind the `data_ingestion/providers/` Protocol; **OpenInsider for Phase-1 prototype, EDGAR as the hardened provider.** Implies an `insider_transactions` DB table (shared with fundamental stream — de-dupe ownership).

### 3.2 Institutional ownership (13F)

**Why limited:** 13F holdings are filed **within 45 days after quarter-end** — by publication the positions are 1.5–4.5 months stale. This is **confirmation, not prediction.**

| Signal | Use | Horizon | Verdict |
|---|---|---|---|
| **New / increased institutional positions** | Quality/conviction filter | quarters | Selective — confirmation only |
| **Concentration of "smart" funds** (low-turnover, high-conviction managers) | Filter for which names "good money" holds | quarters | Selective |

**Data:** SEC EDGAR 13F-HR filings (free, XML/INFOTABLE). **Verdict:** **Use only as a slow quality filter**, never a timing signal. Low priority for a daily system; defer.

### 3.3 Unusual options activity

**Defining "unusual":** single-day volume **≥10× the 20-day average** on a specific strike/expiry, especially out-of-the-money calls with volume > open interest (new positioning), often **ahead of known catalysts** (earnings, FDA). It is a genuine informed-money footprint *intraday*.

| Question | Answer |
|---|---|
| Can daily yfinance snapshots detect it? | **Weakly.** `Ticker.option_chain()` gives an end-of-day snapshot of volume & OI per contract. We can compute "today's contract volume vs OI" but **not the intraday sweep/block detail** that defines true unusual flow. Snapshot pulls are slow and heavy for the full watchlist on a Pi. |
| Free vs paid | True unusual-flow products (**Unusual Whales, Market Chameleon, FlowAlgo**) are **paid** and **intraday** → Phase 2. |

**Verdict:** **Avoid in Phase 1.** The signal's alpha is intraday; our daily snapshot is a degraded proxy that's also compute-heavy. Revisit in Phase 2 with a paid flow feed.

### 3.4 Dark pool volume

**What it is:** off-exchange (ATS) executed volume as a % of total — high off-exchange share can proxy institutional accumulation/distribution.

**Data:** FINRA publishes **ATS / OTC transparency** weekly (Tier 1 with ~2-week lag) as bulk downloads, free. There is no free *real-time* dark-pool print feed (those are paid, e.g., via market-data vendors).

**Verdict:** **Selective / low priority.** The free FINRA data is **aggregated and lagged (~2 weeks, weekly cadence)** — usable only as a slow institutional-interest tilt, not timing. The high-value version (real-time dark-pool prints / DIX) is paid → Phase 2. Defer.

### 3.5 SEC 8-K filings — material-event detection

**Why:** 8-Ks report **material events** (item codes: 1.01 material agreement, 2.02 results, 5.02 exec departure, 4.02 non-reliance/restatement = strong bearish, 8.01 other). Filed **within 4 business days** of the event. They are the earliest *structured, free, authoritative* signal of a corporate event — often before sentiment/news fully diffuse.

| Construct | Definition | Horizon | Direction | Verdict |
|---|---|---|---|---|
| **8-K item-code detection** | Map item code → event type → directional prior | days–weeks | Per code (e.g., 4.02 restatement = bearish; 1.01 big deal = context) | **Use** — cheap, authoritative |
| **Keyword polarity scan** | Scan 8-K text for bullish ("record", "raises guidance", "exceeds") vs bearish ("restate", "default", "investigation", "going concern", "resign") terms | days–weeks | Per polarity | **Use** — simple keyword scoring, Pi-friendly |
| **Filing-burst detection** | Unusual frequency of 8-Ks for a name | days | Elevated corporate activity / risk | Selective |

**Data:** SEC EDGAR Full-Text Search (`efts.sec.gov/LATEST/search-index?forms=8-K&dateRange=custom...`) — free, no key, **10 req/sec**, full archive; plus per-CIK submissions JSON to enumerate recent 8-Ks. **Python:** `requests` with mandatory `User-Agent: <name> <email>` header; parse item codes from the filing index/header.

**Verdict:** **Use.** Pair item-code priors with a lightweight keyword polarity scan. Lead-time opportunity: the filing appears before most retail news aggregation, and the directional drift on items like restatements/guidance is multi-day → daily-batch can act in time.

---

## Cross-stream de-duplication note

Three signals appear in more than one Phase-0A stream; synthesis must assign single ownership to avoid double-counting in the composite:
- **PEAD / earnings surprise** — fundamental stream owns SUE computation; this stream owns the *drift event-tag*. Recommend: fundamental computes SUE, this stream's PEAD tag consumes it.
- **VIX / regime** — technical stream uses VIX as a regime gate; here it is a contrarian sentiment input. Single VIX series, two consumers — fine, but only one should feed the composite weight.
- **Insider Form 4** — appears in both fundamental and this stream. Recommend a single `insider_transactions` provider/table owned here (smart-money), consumed by both.

---

## Handoff notes

**What this document produced:** An evidence-ranked catalogue of news/event, market-sentiment, and smart-money signals — each with horizon, direction, evidence strength, and a Use/Selective/Avoid verdict under the daily-batch + free-tier constraints — plus a data-source evaluation (endpoint, auth, free-tier limit, historical depth, Python access) for every source.

### Sources actually usable for a once-daily batch (and which are not)

| Source | Usable? | Why |
|---|---|---|
| **Finnhub** (company news + SEC filings) | **Yes — primary news** | 60 calls/min free covers ~50 symbols/day; includes pre-scored news endpoint |
| **SEC EDGAR EFTS + submissions** (Form 4, 8-K) | **Yes — primary smart-money** | Free, no key, 10 req/sec, full archive; UA header required |
| **OpenInsider** (Form 4 prototype) | **Yes — prototype** | Free scrape, pre-parsed cluster screens |
| **yfinance** (`^VIX`,`^VIX9D`,`^VIX3M`, short interest, option snapshots) | **Yes (partial)** | VIX/term-structure & short-interest fields good; option chains heavy/EOD-only |
| **CBOE** put/call daily CSV | **Yes** | Free daily market-wide P/C |
| **Alpha Vantage NEWS_SENTIMENT** | **Limited** | Best pre-scored sentiment but **25 req/day** → market-wide pull only, not per-symbol |
| **FINRA** short interest / ATS bulk | **Yes (low-frequency)** | Bi-monthly (short int.) / weekly-lagged (dark pool); fine for week-horizon signals |
| **CNN Fear & Greed** | **No (fragile)** | No official API; undocumented endpoint only → rebuild from components instead |
| **alternative.me** | **No (wrong asset)** | CRYPTO-only — not an equity gauge. Correction to CLAUDE.md table |
| **NewsAPI.org** | **No** | Dev-only, delayed articles, no sentiment, $449/mo paid jump |
| **Unusual Whales / Market Chameleon / DIX** | **No (Phase 2)** | Paid + intraday alpha |
| **pytrends / StockTwits / Reddit** | **Selective** | Unofficial/fragile scrapers; attention proxy only, low weight |

### Priority ranking of signals by evidence strength (strongest validated alpha first)

1. **Insider open-market BUYING (Form 4), cluster + role-weighted** — strongest free smart-money alpha; 1–6 month horizon; EDGAR/OpenInsider. **Implement first.**
2. **PEAD event-tag** (decaying bonus after confirmed earnings beat/miss) — most-replicated event anomaly; 1–3 month drift. (Consumes fundamental stream's SUE.)
3. **8-K material-event detection** (item-code priors + keyword polarity) — timely, authoritative, cheap; days–weeks.
4. **Market-wide contrarian sentiment composite** (VIX level + VIX term-structure backwardation + put/call) — regime/risk-on-off overlay; days–weeks.
5. **News sentiment momentum & divergence** (Finnhub-scored, 3d-vs-14d z-score) — secondary tilt; 3–10 days.
6. **Short-interest trend + days-to-cover** — bearish-conviction / squeeze input; weeks.
7. **13F / dark-pool / retail-attention** — slow filters / attention flags only; low weight.
8. **Unusual options flow, per-symbol skew/IV** — **Phase 2** (intraday + paid).

### Signal latency — when each source's data is available each day (drives job scheduling)

| Source | Availability / lag | Implication for `fetch_news_sentiment()` (06:15 UTC) |
|---|---|---|
| **News (Finnhub/RSS)** | Continuous; previous US session fully available by early UTC morning | Daily pull captures the prior session — well-timed |
| **CBOE put/call** | Prior trading day, published evening ET (~before 06:15 UTC next day) | T-1 value available daily |
| **VIX / term structure (yfinance)** | Prior session close | T-1 available daily |
| **SEC 8-K (EDGAR)** | Within **4 business days** of event; filings appear continuously, many after-hours | Daily scan of last ~5 days catches all |
| **Insider Form 4 (EDGAR/OpenInsider)** | Filed within **2 business days** of transaction | Daily scan of last ~3 days; act on filing day, drift follows |
| **FINRA short interest** | Bi-monthly; published **7th business day after settlement** | Refresh only on publication days; cache between |
| **FINRA dark-pool/ATS** | Weekly, ~2-week lag | Weekly refresh; slow tilt only |
| **13F** | Quarterly, **45-day** post-quarter lag | Refresh after each 13F deadline; confirmation only |
| **AAII survey** | Weekly (Thursday) | Weekly refresh |
| **Google Trends / social** | Daily but rate-limited/fragile | Best-effort daily; tolerate gaps |

### Open questions / decisions deferred to synthesis (00-signal-synthesis.md)

1. **Per-symbol vs market-wide split:** sentiment signals here are mostly market-wide (one value/day). How does the composite blend a *global* risk-on/off overlay with the technical/fundamental *cross-sectional* per-symbol ranks? Recommend: global sentiment scales gross exposure / tilts weights, not per-symbol score.
2. **PEAD ownership:** confirm fundamental stream computes SUE and this stream's decaying PEAD tag consumes it (avoid double count).
3. **Fear & Greed substitute:** approve rebuilding F&G from owned components (VIX + put/call + breadth + momentum) instead of scraping CNN. Correct the CLAUDE.md data table (alternative.me is crypto-only).
4. **Insider provider choice:** OpenInsider (fast prototype) vs SEC EDGAR (durable) — pick one to harden in Phase 4; both behind the same Protocol.
5. **New DB tables implied:** `insider_transactions`, `sec_filings` (8-K item codes + polarity score), `news_sentiment` (per-symbol daily score + volume), `market_sentiment` (daily VIX/term-structure/put-call/short-interest series). Hand to Database Optimizer.
6. **Sentiment NLP boundary:** confirm we rely solely on pre-scored APIs (no on-Pi transformer) — keyword scoring only for 8-K text. Validate against the performance budget with AI Engineer.
