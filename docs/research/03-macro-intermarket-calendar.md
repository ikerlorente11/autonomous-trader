<!-- Agent: Financial Analyst | Phase: 0A | Depends on: [] -->

# Phase 0A — Macro, Intermarket & Calendar Signals Research

**Stream:** Macro regime + intermarket relationships + calendar/seasonal effects
**Goal:** Identify *top-down* signals that classify the market environment and bias the whole portfolio ahead of moves — a regime layer that multiplies/filters the bottom-up stock signals from stream 01.

> Scope note: This stream does NOT pick individual stocks. It answers "what kind of market are we in, and should we be aggressive, cautious, or defensive *today*?" Three filters apply to every recommendation: (1) computable from **FRED** (free, one key) or **yfinance** (free, no key) at daily/weekly/monthly frequency; (2) cheap on ARM64/4GB — a handful of macro series and ETF tickers, not 500-component scans; (3) grounded in published market history, with decayed effects flagged honestly. **Every threshold below is a named config key for `config/strategy.yaml` — nothing is hardcoded.**

> A recurring caveat for the whole stream: macro signals are **low-frequency and slow**. They change the *posture* over weeks-to-months, not the daily trade. Their job is to be a coarse dial (Risk On / Caution / Risk Off), not a precise timer.

---

## SECTION 1 — MACRO REGIME SIGNALS

### 1.1 Interest rate environment

| Signal | FRED series | Native freq | What it predicts | Horizon |
|---|---|---|---|---|
| **Yield-curve slope (10Y−2Y)** | `DGS10` − `DGS2` | Daily | Inversion (spread < 0) precedes recession; **re-steepening from inversion** (un-inversion) is the sharper near-term equity warning | Recession 6–18 mo; equity stress often nearer the un-inversion |
| **Curve (10Y−3M)** | `DGS10` − `DGS3MO` | Daily | The Fed's preferred recession-probability curve (Estrella/Mishkin); same direction as 2-10 but cleaner statistically | 6–18 mo |
| **Rate direction & level** | `DGS10`, `DGS2` 3-month change | Daily | *Rising* long rates pressure long-duration growth/Tech, help Financials (net-interest margin) and Value; *level* matters less than *direction/velocity* for equities | weeks–months |
| **Fed funds trajectory** | `DFEDTARU` (upper target) | Daily/on-meeting | Hiking cycle = headwind/multiple compression; **first cut** historically a tradeable inflection (but "cutting into recession" is bearish, "cutting into soft landing" is bullish — context-dependent) | quarters |
| **Real 10Y rate** | `DGS10` − `T10YIE` (10Y breakeven) | Daily | Real yields are the cleanest equity-valuation discount rate. Rising real rates compress P/E multiples (esp. growth) | weeks–months |

**Key interpretations grounded in history:**
- **Yield-curve inversion (2-10 < 0):** the most reliable single recession lead in the post-war record (every US recession since 1955 preceded by inversion; ~1–2 false-ish signals). But the *lag is long and variable (6–18 months)* and equities often rally *after* inversion before topping. **Do not treat inversion as a sell signal — treat it as a "raise caution ceiling" signal.** The sharper trigger is **re-steepening after a deep inversion**, which has clustered near the start of equity drawdowns.
- **Real rates:** historically, **real 10Y above ~2%** has coincided with equity-multiple pressure, particularly for long-duration growth. Express as config, not gospel — the threshold drifts with the structural regime.
- **Rate direction > level:** a 4% 10Y that is *falling* is risk-on; a 4% 10Y *spiking* is risk-off. Use 3-month change, not the absolute level, as the primary equity input.

Config keys: `macro.curve.inversion_threshold_bps: 0`, `macro.curve.steepening_trigger_bps: 25`, `macro.real_rate.equity_pressure_threshold_pct: 2.0`, `macro.rate.direction_lookback_days: 63`.

### 1.2 Inflation signals

| Signal | FRED series | Native freq | Release lag | Market relevance |
|---|---|---|---|---|
| **CPI (headline)** | `CPIAUCSL` | Monthly | ~2 weeks | The headline number markets *react* to; high-emotion print |
| **Core PCE** | `PCEPI` (+ core variant) | Monthly | ~4 weeks | **The Fed's actual target gauge** — moves policy expectations more than CPI over time |
| **PPI** | `PPIACO` | Monthly | ~2 weeks | Producer/upstream inflation; *leads* CPI for goods, useful early read on margin pressure |

**Sector winners/losers:**
| Inflation regime | Winners | Losers |
|---|---|---|
| **High / rising** | Energy, Materials, Financials (rate beneficiaries), some Real Estate (pricing power) | Long-duration Tech, Consumer Discretionary, Utilities (rate proxy), zero-margin growth |
| **Low / falling** | Tech/growth (low discount rate), Discretionary | Energy, Materials, commodity producers |

**Mechanics that matter:**
- **CPI vs PCE market impact:** CPI is the *headline shock* (markets gap on the print); **PCE is what actually steers the Fed** and therefore the medium-term rate path. CPI moves stocks on the day; PCE moves the policy regime. Track both, weight PCE for *regime*, CPI for *event risk*.
- **Inflation surprise (actual − consensus)** is what moves markets, not the level. A high print that *undershoots* expectations is bullish. ⚠️ **Consensus data is NOT in FRED or yfinance** — it requires a calendar/estimates provider (Phase 2). Phase 1 fallback: proxy "surprise" as deviation from a trailing trend (e.g., MoM vs 6-month average), which is weaker but free.

Config keys: `macro.inflation.surprise_source: trend_proxy|consensus`, `macro.inflation.high_regime_yoy_pct: 4.0`, `macro.inflation.weight_pce_for_regime: 0.6`.

### 1.3 Economic cycle phase detection

| Signal | FRED series | Freq | Reads |
|---|---|---|---|
| **Leading index** | `USSLIND` (state leading idx) or `USALOLITONOSTSAM` (OECD CLI) | Monthly | Direction of the cycle; turning points |
| **Manufacturing proxy** | `MANEMP` (mfg employment) — ISM PMI itself is **not free on FRED** | Monthly | Cyclical pulse; use direction (3-mo change) as a >50/<50 proxy |
| **Payrolls** | `PAYEMS` (NFP) | Monthly | Growth confirmation |
| **Jobless claims** | `IC4WSA` (4-wk avg initial claims) | **Weekly** | The most *timely* labor signal; rising claims lead downturns |
| **Consumer confidence** | `UMCSENT` (Michigan) | Monthly | Demand/sentiment; mean-reverting |

> ⚠️ **ISM Manufacturing PMI is proprietary and not on FRED.** The brief references "PMI>50" as shorthand. Phase-1 free substitute: use **`MANEMP` 3-month rate of change** and the **OECD CLI direction** as the "PMI proxy." Where this doc says PMI it means *this proxy*. A true ISM/PMI feed is Phase 2 (paid/scraped).

**"Bad news = good news" asymmetry:** in a *Fed-tightening regime*, weak labor/soft data can rally stocks (markets price earlier cuts); in a *recession regime*, weak data is straightforwardly bearish (earnings risk dominates). The sign of the reaction flips with the Fed posture — so this asymmetry must be **gated by `DFEDTARU` direction**, not applied blindly.

**Concrete regime-classification rule (expansion / peak / contraction / trough):**

| Phase | Rule (all config-thresholded) |
|---|---|
| **Expansion** | Leading index rising (3-mo Δ > 0) **AND** PMI-proxy direction up **AND** claims falling |
| **Peak** | Leading index flattening/rolling (3-mo Δ ≈ 0 after positive run) **AND** PMI-proxy decelerating **AND** curve flat/inverted |
| **Contraction** | Leading index falling (3-mo Δ < 0) **AND** claims rising **AND** PMI-proxy < proxy-neutral |
| **Trough** | Leading index stops falling / turns up after a contraction **AND** claims peaking & rolling over |

Config keys: `macro.cycle.lei_lookback_months: 3`, `macro.cycle.pmi_proxy_series: MANEMP`, `macro.cycle.claims_trend_weeks: 13`.

### 1.4 Sector rotation model

Classic economic-cycle rotation (Sam Stovall / Fidelity business-cycle framework):

| Cycle phase | Favored sectors | ETF tickers | Rationale |
|---|---|---|---|
| **Early expansion** (trough→recovery) | Financials, Consumer Discretionary, Industrials | XLF, XLY, XLI | Rate-sensitive + cyclical demand snaps back first |
| **Late expansion / peak** | Energy, Materials, Technology | XLE, XLB, XLK | Inflation/commodities run hot; capex & late-cycle growth |
| **Early contraction** (slowdown) | Utilities, Consumer Staples, Healthcare | XLU, XLP, XLV | Defensive, inelastic demand, low beta |
| **Late contraction / trough** | Technology recovering, Financials | XLK, XLF | Rate cuts + early-cycle leaders begin discounting recovery |

**Reliability — be honest:** sector rotation is **directionally real but noisy and unreliable as a precise timer.** The macro lags are long and variable; the framework is right "on average over cycles" but produces many false rotations mid-cycle. Treat it as a **tilt** (modest over/underweight to a sector's stock signals), **never** a hard switch. It is most useful at the *extremes* (deep contraction → defensive tilt) and least useful mid-expansion.

**What triggers a rotation:** a confirmed change in the §1.3 phase classifier (e.g., two consecutive monthly reads of leading-index direction flip) — not a single print. Use the relative-strength of sector ETFs vs SPY (computed in stream 01) to *confirm* the macro-implied rotation before acting.

Config keys: `macro.rotation.enabled: true`, `macro.rotation.tilt_strength: 0.15` (max ±15% signal nudge), `macro.rotation.confirm_with_relative_strength: true`, `macro.rotation.phase_confirm_reads: 2`.

---

## SECTION 2 — INTERMARKET RELATIONSHIPS

> All computable from daily yfinance ETF/index downloads — cheap, no component scans. These are *cross-asset confirmation/divergence* signals: when bonds, credit, commodities, FX, and vol agree, conviction is high; when they diverge from equities, the equity move is suspect.

### 2.1 Bonds vs stocks

| Signal | Tickers | Reads |
|---|---|---|
| **High-yield credit spread proxy** | `HYG` ÷ `IEF` (HY corp vs 7-10Y Treasury) ratio | **Falling ratio = credit stress = equity-weakness lead.** Credit usually cracks before equities. The single best intermarket early-warning. |
| **Investment-grade stress** | `LQD` vs `IEF` | Secondary credit read; IG widening confirms broad risk-off |
| **Long-duration risk gauge** | `TLT` (20Y+ Treasury) | Rising TLT in a stock selloff = classic flight-to-safety (risk-off confirmed); rising TLT *with* rising stocks = benign (rates falling for good reasons) |

**When the inverse relationship breaks:** the normal stocks↑/bonds↓ inverse correlation **inverts to positive correlation in two cases:** (1) **risk-off crises** — everything falls except Treasuries (stocks & credit down, TLT up); (2) **inflation/rate shocks** — stocks AND bonds fall together (2022 regime). The *break* itself is information: stock-bond correlation turning positive-and-falling is a regime-change flag.

Config keys: `intermarket.credit.hyg_ief_lookback_days: 21`, `intermarket.credit.stress_drop_pct: 2.0`, `intermarket.stock_bond_corr_window: 63`.

### 2.2 Commodities

| Signal | Tickers | Reads |
|---|---|---|
| **Oil / energy** | `USO`, `XLE` | Rising oil = inflation + (to a point) growth; oil *spikes* are a late-cycle/recession risk; energy-sector RS confirms inflation regime |
| **Gold** | `GLD` | Flight-to-safety + real-rate inverse; gold up *with* falling real rates = risk-off/debasement hedge |
| **Copper ("Dr. Copper")** | `CPER` or `COPX` (miners proxy) | Global industrial-growth barometer; copper rolling over leads industrial slowdown |
| **Broad commodity trend** | `DBC` | Inflation vs deflation regime read; trend up = inflation regime (favors Energy/Materials) |
| **Copper/Gold ratio** | `CPER` ÷ `GLD` | Growth-vs-fear ratio; rising = pro-growth/pro-cyclical, often tracks the 10Y yield |

**Honest note:** single-commodity ETFs (USO, CPER) carry **roll/contango drag** and are imperfect proxies for spot. Use them for *trend/direction* signals only, never level. Copper/Gold ratio is a well-regarded macro-growth tell but is noisy week-to-week.

Config keys: `intermarket.copper_gold.lookback_days: 63`, `intermarket.commodity_trend_ma_days: 100`.

### 2.3 Currencies

| Signal | Tickers | Reads |
|---|---|---|
| **US Dollar index** | `UUP` (DXY bullish ETF) | **Strong/rising dollar hurts US multinationals** (foreign revenue translation) and pressures commodities & EM; a fast dollar spike is a global risk-off tell |
| **EM stress** | `EEM`, `FXI` | EM equities/currencies break *before* global risk-off; EEM relative weakness is an early de-risking signal |

**S&P sectors by FX/foreign-revenue exposure (highest → lowest):** Technology, Materials, Communication Services, Industrials have the **highest foreign-revenue share** (~50%+) → most hurt by a strong dollar. Utilities, Real Estate, Financials, Consumer Staples are the most **domestic** → relatively insulated. So a **rising-dollar regime should tilt the scorer toward domestic sectors.**

Config keys: `intermarket.dollar.spike_lookback_days: 21`, `intermarket.dollar.spike_pct: 3.0`, `intermarket.dollar.tilt_domestic_sectors: true`.

### 2.4 Volatility

| Signal | Tickers | Reads |
|---|---|---|
| **VIX level** | `^VIX` | **<20 = complacent/risk-on; 20–30 = caution; 30–40 = stress; >40 = panic/capitulation** (often a contrarian bounce zone). |
| **VIX term structure** | `^VIX` ÷ `^VIX3M` | Normal = contango (spot < 3M, ratio <1). **Ratio >1 (backwardation, spot > 3M) = acute danger / fear pulled forward** — the cleaner risk-off trigger than VIX level alone. |
| **VVIX (vol of vol)** | `^VVIX` | Spikes warn of fragility before VIX itself moves; >~110–120 flags unstable conditions |

`^VIX3M` ticker on yfinance is `^VIX3M`; if unavailable, fall back to `VXV`. VVIX = `^VVIX`.

**Mechanics:** VIX is mean-reverting and *spikes* (asymmetric). The **term-structure ratio is the best single risk-off switch** because it captures fear *acceleration* — a low VIX can still be in backwardation right before trouble. Very high VIX (>40) is paradoxically a *mean-reversion long* signal historically (panic = local bottom), so the regime filter should **stop adding risk-off pressure above an extreme threshold** to avoid selling the bottom.

Config keys: `intermarket.vix.complacent_below: 20`, `intermarket.vix.caution_above: 20`, `intermarket.vix.stress_above: 30`, `intermarket.vix.panic_above: 40`, `intermarket.vix.term_structure_danger_ratio: 1.0`, `intermarket.vvix.fragility_above: 110`.

### 2.5 Market breadth

| Signal | What it reads | Cost concern |
|---|---|---|
| **% of S&P 500 above 200d MA** | <30% = washout/oversold; >80% = overbought/late | Needs 500 components |
| **Advance/Decline line divergence** | A/D making lower highs while index makes higher highs = deteriorating participation = top warning | Needs component-level data |
| **New 52wk highs vs lows** | Expanding new-lows while index rises = narrowing leadership | Needs components |
| **McClellan Oscillator** | EMA of net advances; breadth momentum | Needs components |
| **Sector new-highs while index stalls** | Rotation/leadership read | Needs components |

**Pi RAM/time cost — this is the binding constraint of this section.** Downloading all ~503 S&P components daily via yfinance is **slow (rate-limited, minutes), fragile (failures/delistings), and RAM-heavy** for a 4GB Pi. **Do NOT compute true breadth from components in Phase 1.**

**Lightweight breadth proxy (recommended):** use **breadth ETFs and equal-weight spreads** instead of component scans:
- **RSP ÷ SPY** (equal-weight vs cap-weight): falling = breadth narrowing (mega-cap-only rally) = fragile. This single ratio captures most of the A/D-divergence information for the cost of two daily bars.
- **IWM ÷ SPY** (small vs large): small-cap relative weakness = risk-off/late-cycle.
- **^NYHL / breadth indices**: if a free high/low net index is available via yfinance, ingest it directly (one series) rather than recomputing.
- Optional Phase-2 upgrade: compute true % >200MA on the **~60-symbol watchlist only** (not 500) as a sampled breadth proxy — cheap and already downloaded.

Config keys: `breadth.method: etf_proxy|watchlist_sample|full_components`, `breadth.rsp_spy_lookback_days: 63`, `breadth.pct_above_200ma_washout: 30`, `breadth.pct_above_200ma_overbought: 80`.

---

## SECTION 3 — CALENDAR & SEASONAL EFFECTS

> These are **deterministic, free, zero-data-cost** signals — pure date math plus the watchlist earnings calendar. They modulate position *timing/sizing*, not direction. Honesty flags included: several classic effects have **decayed** post-publication.

### 3.1 Earnings season effects

- **Timing:** ~80% of the S&P reports in **weeks 2–5 after each calendar-quarter end** — i.e., clusters in **mid-Jan→Feb, mid-Apr→May, mid-Jul→Aug, mid-Oct→Nov.** Big banks kick off; mega-cap Tech lands in the back half.
- **Pre-earnings drift:** stocks with positive momentum/revision tend to drift up *into* the print (anticipation). Mild, exploitable as a small pre-event tilt for already-strong names.
- **Post-earnings-announcement drift (PEAD):** the documented edge — returns drift in the direction of the earnings *surprise* for **~20–60 days** post-report (Bernard & Thomas). This is the calendar hook for stream 01's SUE signal: **the calendar tells us *when* the PEAD window opens.**
- **Earnings-season market uplift:** broad market has a mild upward bias during heavy reporting weeks (beats > misses on average due to lowballed guidance).
- **"Sell the news":** a beat that *gaps up then fades* (closes weak on high volume) flags exhausted positioning — a reversal/avoid signal. Identify via gap-up + intraday/close-below-open + volume (daily-bar approximation: open vs close on the report day).

Config keys: `calendar.earnings.pead_window_days: 45`, `calendar.earnings.pre_drift_days: 5`.

### 3.2 FOMC effects

- **8 meetings/year** (scheduled, known dates — hardcode the annual calendar via config, refreshed yearly).
- **"Fed drift" / pre-FOMC announcement drift:** a well-documented historical anomaly — abnormally positive equity returns in the **~24 hours before FOMC announcements** (Lucca & Moench, NY Fed). **Honesty flag: this effect has weakened/become less reliable since it was published (~2015)** — treat as a small, low-confidence tilt, not a core signal.
- **Rate-decision surprise:** measured as decision vs market-implied (Fed funds futures) expectation. ⚠️ Futures-implied probability is **not free in yfinance/FRED** — Phase 1 proxy: compare actual `DFEDTARU` change to the prior consensus path (weak). Real surprise measurement is Phase 2.
- **Post-statement drift/reversal:** the post-2pm reaction often **reverses** in the following days as the knee-jerk move fades; raises near-term realized vol regardless of direction. → **reduce position sizing on FOMC day** rather than predict direction.

Config keys: `calendar.fomc.dates: [...]` (annual list), `calendar.fomc.pre_drift_tilt: 0.0` (default off — decayed), `calendar.fomc.reduce_sizing_on_day: true`.

### 3.3 Options-expiration (OpEx) effects

- **Monthly 3rd-Friday gamma "pinning":** large open interest can pull price toward high-OI strikes ("max pain") as dealers hedge. Real but **noisy and hard to exploit without options OI data** (Phase 2, paid).
- **Quarterly Triple Witching** (3rd Fri of Mar/Jun/Sep/Dec): index futures + index options + stock options expire together → elevated volume and intraday volatility, frequent late-day swings.
- **Week-after reversal:** the week *following* monthly OpEx has shown a mild negative/mean-reverting bias historically (positioning unwind) — weak, decayed.
- **Max-pain theory:** folkloric; **little robust out-of-sample evidence.** Flag as low-confidence; do not weight.

**Daily-system takeaway:** we can't compute gamma/max-pain without options OI (Phase 2). What's free and useful: **flag OpEx Fridays and Triple-Witching days as elevated-vol / reduce-sizing days** via pure date math.

Config keys: `calendar.opex.reduce_sizing_on_triple_witching: true`, `calendar.opex.flag_monthly_opex: true`.

### 3.4 Seasonal patterns — honest edge assessment

| Effect | Academic name | Original claim | Edge today |
|---|---|---|---|
| **January Effect** | Keim small-firm January | Small-caps outperform in Jan | **Largely decayed** — arbitraged away; weak |
| **Sell-in-May / Halloween** | Halloween indicator (Bouman & Jacobsen) | Nov–Apr >> May–Oct | **Surprisingly persistent** across many markets; the most robust seasonal — but modest and not every year. Keep as a *mild* tilt |
| **September Effect** | September seasonality | September is the worst month historically | **Real but weak/noisy**; small negative bias, high variance |
| **End-of-quarter window dressing** | Window dressing | Funds buy winners near quarter-end | Mild, present, hard to isolate |
| **Pre-holiday effect** | Holiday effect | Positive returns before market holidays | **Decayed**; tiny |
| **Monday Effect / weekend** | Weekend effect (French) | Mondays negative | **Largely gone** — decayed/reversed in modern data |

**Verdict:** only **Sell-in-May/Halloween** and a faint **September** bias retain any defensible edge, and both are *modest seasonal tilts*, not signals to act on alone. The rest are **decayed** — include them only as near-zero-default config tilts so they can be experimented with, never as core weights.

Config keys: `calendar.seasonal.halloween_tilt: 0.05`, `calendar.seasonal.september_tilt: -0.03`, `calendar.seasonal.january_effect: 0.0`, `calendar.seasonal.monday_effect: 0.0` (defaults express "decayed → off").

### 3.5 Earnings pre-announcement calendar (for the watchlist)

- **Build:** for each watchlist symbol, pull next earnings date from **`yfinance` `get_earnings_dates()` / `calendar`** (free). Nasdaq earnings calendar is a free fallback. Refresh daily for the watchlist (~60 symbols = cheap).
- **Position scaling around earnings:** earnings introduce **binary gap risk** that defeats daily prediction. Recommended rule: **scale position size DOWN starting N days before a report** (avoid holding full size into a coin-flip), then **scale back UP into the PEAD window** *after* the surprise is known (capturing drift, not gambling on the gap).

Config keys: `calendar.earnings.derisk_days_before: 3`, `calendar.earnings.derisk_size_factor: 0.5`, `calendar.earnings.reengage_after_report: true`.

---

## SECTION 4 — MACRO REGIME FILTER (the synthesis)

The deliverable of this stream: a single **regime classifier** that outputs `RISK_ON | CAUTION | RISK_OFF` and acts as a **multiplier on every bottom-up stock score** from stream 01.

### 4.1 Regime classification

Score each input as a vote, combine, and classify. All thresholds are config keys.

| Input | RISK_ON vote | CAUTION vote | RISK_OFF vote | Source |
|---|---|---|---|---|
| Yield curve (10Y−2Y) | Normal/steepening (>0) | Flattening toward 0 | Inverted then **re-steepening** | FRED |
| Cycle phase (§1.3) | Expansion | Peak | Contraction | FRED |
| VIX level | < 20 | 20–30 | > 30 | yfinance |
| VIX term structure | < 1 (contango) | ≈ 1 | > 1 (backwardation) | yfinance |
| Credit (HYG/IEF) | Rising/stable | Drifting down | Falling fast (>stress%) | yfinance |
| Breadth (RSP/SPY) | Rising/broad | Narrowing | Falling hard | yfinance |
| SPY vs 200d MA | Above | Near/whipsaw | Below | yfinance |

**Headline regime definitions (the chosen defaults):**

| Regime | Trigger (any of the strong conditions; majority vote otherwise) | Scoring effect |
|---|---|---|
| **RISK_ON** | Yield curve normal **AND** PMI-proxy rising (expansion) **AND** VIX < 20 **AND** credit stable | **Aggressive:** multiplier **1.0–1.2**, full position sizes, momentum profile favored |
| **CAUTION** | Curve flattening **OR** cycle = peak **OR** VIX 20–30 **OR** breadth narrowing (RSP/SPY falling) | **Reduce:** multiplier **~0.6**, smaller sizes, raise quality/defensive tilt |
| **RISK_OFF** | VIX > 30 **OR** VIX term-structure > 1 **OR** credit spreads widening fast **OR** SPY < 200d MA | **Defensive:** multiplier **~0.3 (toward cash)**, defensive sleeve (XLU/XLP/XLV) only, mean-reversion profile, **except** suspend further de-risking when VIX > 40 (panic = contrarian bottom) |

Use a **hysteresis / confirmation rule** (regime must hold ≥2 days before switching) to avoid whipsawing the whole portfolio on a one-day VIX spike.

### 4.2 How regime multiplies / filters stock signals

The regime is **not a separate signal in the composite** — it is a **post-multiplier** on the final per-symbol score from stream 01:

```
final_score(symbol) = composite_score(symbol)            # from stream 01
                     × regime_multiplier                  # RISK_ON 1.0–1.2 / CAUTION 0.6 / RISK_OFF 0.3
                     × sector_rotation_tilt(symbol_sector) # ±15% per §1.4
                     × calendar_size_factor(symbol, date)  # earnings/FOMC/OpEx de-risking
```

Concrete interaction examples:
- A great technical setup (composite 0.9) in **RISK_OFF** → 0.9 × 0.3 = **0.27** → won't make the buy cutoff. Correct: don't fight a risk-off tape.
- A mediocre defensive name (0.5) in **RISK_OFF** gets the defensive-sector tilt and survives relative ranking.
- The regime also **switches the per-symbol regime profile** (stream 01's momentum-vs-reversion classifier): RISK_ON → momentum profile; RISK_OFF → reversion/defensive profile. This must be reconciled in `00-signal-synthesis.md` so the two regime layers (global macro + per-symbol) don't double-count.

### 4.3 Consolidated config block (proposed `config/strategy.yaml` shape)

```yaml
regime:
  hysteresis_days: 2
  multipliers:
    risk_on: 1.1
    caution: 0.6
    risk_off: 0.3
  risk_off_panic_floor_vix: 40   # above this, stop adding risk-off pressure
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
```

---

## Handoff notes

**What this document produced:** a FRED+yfinance catalog of macro/intermarket/calendar signals (with native frequencies, release lags, and honesty flags on decayed effects), a four-phase economic-cycle classifier, a sector-rotation matrix, a lightweight breadth approach that avoids 500-component scans, and a **RISK_ON/CAUTION/RISK_OFF regime filter** that acts as a config-driven multiplier on stream 01's stock scores.

### 1. Free vs paid data
- **Free (FRED, one key):** all yield-curve, rate, real-rate, inflation (CPI/PPI/PCE), leading index, claims, payrolls, consumer confidence series. **Free (yfinance, no key):** all intermarket ETFs/indices (HYG, IEF, TLT, LQD, USO, GLD, CPER, DBC, UUP, EEM, FXI, RSP, IWM, ^VIX, ^VIX3M, ^VVIX), watchlist earnings dates, FOMC/OpEx via date math.
- **Phase 2 (paid/unavailable free):** **ISM PMI** (proprietary — using `MANEMP` proxy in Phase 1), **economic-data consensus/surprise** (inflation & rate surprise need a calendar provider), **rate-decision surprise** (Fed funds futures), **options OI / gamma / max-pain** (OpEx pinning). All flagged inline.

### 2. Proposed regime thresholds (config defaults)
- Multipliers: **RISK_ON 1.1, CAUTION 0.6, RISK_OFF 0.3**, with a **VIX>40 panic floor** that suspends further de-risking. Switches: **VIX 20/30/40**, **VIX term-structure ratio > 1.0**, **curve inversion 0bps + re-steepening 25bps trigger**, **real-rate pressure 2.0%**, **credit (HYG/IEF) stress drop 2%**, **SPY vs 200d MA**, **2-day hysteresis**. Full block in §4.3.

### 3. For the Database Optimizer
- **Series to store — macro (FRED, low volume):** `DGS2, DGS10, DGS3MO, T10YIE, DFEDTARU, CPIAUCSL, PPIACO, PCEPI, USSLIND, MANEMP, PAYEMS, IC4WSA, UMCSENT`. Frequencies: **daily** (rates/breakeven), **weekly** (claims), **monthly** (CPI/PPI/PCE/LEI/employment/sentiment).
- **Series to store — intermarket (yfinance daily OHLCV):** reuse the existing `market_bars` hypertable — these are just more tickers (HYG, IEF, TLT, LQD, USO, GLD, CPER, DBC, UUP, EEM, FXI, RSP, IWM, ^VIX, ^VIX3M, ^VVIX). **No new table needed for intermarket.**
- **New table needed — `macro_series`:** suggested shape `(series_id TEXT, ts TIMESTAMPTZ, value NUMERIC, release_ts TIMESTAMPTZ NULL)` → TimescaleDB hypertable partitioned on `ts`, primary key `(series_id, ts)`. Tiny: ~13 series × mostly monthly/daily ≈ **a few thousand rows for years of history; <1 MB.** Negligible on the Pi.
- ⚠️ **Point-in-time / revisions concern:** **FRED data is revised** (CPI, NFP, LEI get restated for months). The `value` for a given `ts` *changes over time*. For live trading this is harmless (use latest), but for any backtest it creates **look-ahead bias**. Recommend storing `release_ts` (when the value was first published) and, if the Experiment Tracker needs true point-in-time, use **FRED ALFRED vintages** later (Phase 2). Flag this to the Experiment Tracker alongside stream 01's point-in-time fundamentals concern.
- **Calendar data:** FOMC dates + market-holiday calendar are tiny static config, not DB tables. Watchlist earnings dates can live in a small `earnings_calendar (symbol, report_date, when)` table refreshed daily.

### Questions for the synthesis step (00-signal-synthesis.md)
1. **Two regime layers:** this stream's *global macro regime multiplier* vs stream 01's *per-symbol momentum/reversion regime*. Synthesis must define how they compose without double-counting (proposal: macro sets the global multiplier + profile bias; per-symbol classifier refines within that).
2. **Breadth method decision:** default to the **ETF-proxy (RSP/SPY, IWM/SPY)** breadth to protect the Pi, with `watchlist_sample` as an opt-in upgrade. Confirm no agent expects true 500-component breadth in Phase 1.
3. **PMI proxy acceptance:** confirm `MANEMP`-direction + OECD CLI is an acceptable Phase-1 stand-in for ISM PMI, with real PMI deferred to Phase 2.
4. **Surprise data:** inflation/rate *surprise* signals need consensus data (not free). Ship the **trend-proxy** version in Phase 1 or wait for a Phase-2 calendar provider? Recommend trend-proxy now, behind a `surprise_source` config switch.
5. **Calendar tilts default-off:** decayed seasonals (January/Monday/pre-holiday) ship as **0.0 defaults** so the Experiment Tracker can test them without them affecting baseline results.
