<!-- Agent: FP&A Analyst | Phase: diagnóstico | Depends on: workflow diagnostico-perdidas -->

# Diagnóstico de pérdidas — Carteras paper (snapshot 2026-06-08)

## Resumen ejecutivo

1. Ambas carteras pierden ~8,1-8,6% vs su capital neto aportado: **Cartera 500** NAV 459,69 € (−8,06%) y **Cartera 100K** NAV 91.430,05 € (−8,57%). El benchmark SPY rebasado cayó solo −2,50%.
2. La mayor parte de la pérdida **no es beta de mercado**: el alfa es **−5,51 a −5,56 pp** (C1) y **−6,02 a −6,07 pp** (C2). En €: **−27,55 €** (C1) y **−6.018,82 €** (C2) por debajo de lo que daría el SPY.
3. La pérdida se reparte ~56-59% **realizada** (C1 −22,47 €, C2 −5.015,20 €) y ~41-44% **latente en posiciones abiertas** (C1 −17,84 €, C2 −3.554,74 €). Reconcilia al céntimo contra la caja.
4. **El 100% de las ventas (8/cartera) son trailing stops** (`protective-sell`); el scorer **nunca vende**. Las salidas son ciegas al alfa: liquidan a −7,4% medio sin reevaluar el score.
5. Hit-rate de round-trips cerrados **12,5%** (1 de 8 ganador, MSFT), **profit factor ~0,01**. El patrón de salidas pierde casi siempre.
6. **Causa raíz #1 (selección, scorer):** el motor compra lo **sobrecomprado y estirado** — RSI passthrough crudo peso 0,50 (BUY a RSI medio 66,6) + ma_trend que premia la extensión. Contradice el diseño aprobado.
7. **Causa raíz #2 (ejecución, stops):** trailing stop ATR×2,5 demasiado ajustado liquida ETFs en ruido normal (SPY −1,5%, VTI −1,7%, QQQ −2,5%) y dispara en cascada (5 stops el 06-05 = 74% del realizado).
8. **Causa raíz #3 (arquitectura):** asimetría protective_sell↔execute_paper_trades sin cooldown → **whipsaw AMD** (stop 06-05 @466,15, recompra 06-08 @466,85, +0,15% más caro).
9. **Síntomas (no causas):** ~49,3% en caja (estructural: 5%×10 + MIN_CASH 20%), benchmark stale/no-idempotente, `unrealized_pnl` fantasma en filas qty=0.
10. **Magnitud central:** ~63% del drawdown de C2 se concentra en Tech-Semis (AMD+AVGO = −5.412,60 €); AMD solo aporta −3.485,91 € (40,7% del drawdown del NAV).

---

## Métricas de rendimiento reales por cartera

| Métrica | Cartera 500 (C1) | Cartera 100K (C2) | Fuente |
|---|---|---|---|
| Capital neto aportado | 500,00 € | 100.000,00 € | `cash_movements` (1 depósito, 0 retiradas) |
| NAV total actual | 459,69 € | 91.430,05 € | `portfolio_nav` último (2026-06-08) |
| Rentabilidad vs aportado | **−8,06%** | **−8,57%** | NAV/aportado − 1 |
| Benchmark (SPY rebasado) | −2,50% | −2,50% | 487,24/499,75−1 ; 97.448,87/99.950−1 |
| **Alfa total** | **−5,51 a −5,56 pp** | **−6,02 a −6,07 pp** | ret_cartera − ret_benchmark |
| Alfa en € (NAV − bench) | **−27,55 €** | **−6.018,82 €** | 459,69−487,24 ; 91.430,05−97.448,87 |
| P&L realizado (stops) | **−22,47 €** (55,7%) | **−5.015,20 €** (58,5%) | avg-cost sobre `trade_orders` |
| P&L latente (abiertas qty>0) | **−17,84 €** | **−3.554,74 €** | Σ qty·(current−avg_cost), 7 posiciones |
| Hit-rate round-trips cerrados | 12,5% (1/8) | 12,5% (1/8) | único ganador MSFT |
| Profit factor (realizado) | ~0,010 | ~0,0091 | 0,22/22,69 ; 46,09/5.061,30 |
| Max drawdown sobre total | −8,82% | −9,20% | pico 06-03 → valle 06-05 |
| Volatilidad diaria | 2,88% | 2,98% | pstdev 10 obs (baja significancia) |
| Sharpe diario / anualizado | −0,274 / −4,35 | −0,282 / −4,48 | rf=0, n=10 (direccional) |
| Caja sobre NAV | 49,3% (226,78 €) | 49,3% (45.049,13 €) | estructural por diseño |
| Posiciones abiertas (qty>0) | 7 | 7 | `portfolio_positions` |
| Comisiones modeladas | 0,00 € | 0,00 € | no existe modelo |
| Slippage modelado | ~0,89 € | ~177 € (≈199×) | SLIPPAGE_PCT=0,001/lado |

> Reconciliación: caja = depósito − Σcompras + Σventas, exacto al céntimo. El `unrealized_pnl` **almacenado** en `portfolio_positions` está **stale** (C1 −28,83 €, C2 −5.855,13 €) porque suma 7 filas con `qty=0` (posiciones ya cerradas con upnl fantasma, incluido el "ganador" MSFT ya vendido). El latente real sobre abiertas es −17,84 €/−3.554,74 €.

---

## Atribución del P&L

### Por tipo de operación (verificado, alta confianza)

| Tipo | C1 | C2 | Nota |
|---|---|---|---|
| Realizado por **scorer-exit** | 0,00 € | 0,00 € | el scorer **nunca vende** (0/8 ventas) |
| Realizado por **protective-sell** | −22,47 € | −5.015,20 € | 8 round-trips, 7 perdedores |
| Latente en abiertas (entradas scorer) | −17,84 € | −3.554,74 € | 7 posiciones, 0 ganadoras (hit-rate 0/7) |

El 100% del realizado se origina en el **trailing stop**, no en decisiones de salida del scorer (SQL: `trade_orders GROUP BY side,strategy_version` → todas las ventas `strategy_version='protective-sell'`).

### Por símbolo — Cartera 100K (realizado por avg-cost)

| Símbolo | Realizado | Tipo |
|---|---|---|
| MSFT | **+46,09 €** | único ganador |
| VTI | −84,59 € | ETF índice (stop en ruido) |
| SPY | −87,25 € | ETF índice (stop en ruido) |
| QQQ | −276,19 € | ETF índice (stop en ruido) |
| AMZN | −351,81 € | |
| TSLA | −464,02 € | |
| AVGO | −981,47 € | semis |
| **AMD** | **−2.815,96 €** | **56% del realizado C2** |

### Por sector/cubo y por día (Cartera 100K)

- **Tech-Semis (AMD+AVGO):** −5.412,60 € = **63,2% del drawdown del NAV** (realizado −3.797,43 + latente −1.615,17).
- **AMD solo:** −3.485,91 € = **40,7% del drawdown del NAV** (realizado −2.815,96 + latente abierto −669,95).
- **Concentración temporal:** −3.728,01 € (74% del realizado) se cristalizó **en un solo día, 2026-06-05**, al saltar 5 stops a la vez (TSLA, QQQ, SPY, VTI, AMD). 3 de esos 5 son ETFs de índice amplio → por definición caída de mercado, no deterioro idiosincrático.

> Nota metodológica: los importes en € son exactos; los porcentajes se fijan aquí sobre el **drawdown del NAV** (base homogénea −8.569,95 €) para evitar la mezcla de denominadores detectada en la verificación.

---

## Causas raíz verificadas

### CR-1 — El scorer compra caro/vende barato (SELECCIÓN) · CAUSA RAÍZ · confianza ALTA

El motor premia sobrecompra y extensión, exactamente el reverso del diseño aprobado.

- **Código:** `backend/analysis/indicators/momentum.py:31-35` (RSI passthrough crudo, sin override de `latest_score`) + `backend/analysis/indicators/base.py:44-49` (pasa el RSI crudo clip 0-100) → peso **0,50** en `config/strategy.yaml:32`. `backend/analysis/indicators/moving_average.py:39-51` (ma_trend = logística de la extensión sobre EMA20, peso 0,30). `backend/analysis/scoring/composite_scorer.py:42-61` (media ponderada lineal: mayor sub-score → mayor composite).
- **Datos:** `corr(composite, RSI)=0,963`, `corr(composite, ma_trend)=0,975`, `corr(composite, ATR)=0,143` (n=196). SQL `algorithm_signals GROUP BY action`: BUY a RSI medio **66,6** (28/73 con RSI≥70), SELL a RSI medio 36,0; BUY a ma_trend medio **69,0** vs SELL 27,9. AMD comprado a ma_sub 95-98 (extremadamente estirado).
- **Contradice el diseño:** `docs/research/00-signal-synthesis.md` §3.2 (RSI regime-conditioned: `rsi_oversold 0,35` reversion / `rsi_bb 0,10` momentum — nunca passthrough 0,50), §3.4 (rank-normalización cross-seccional ausente), §3.1 Step7 (multiplicador macro ausente). El ATR, reservado por el diseño a sizing/stops (§1 línea 27, §3.1 línea 125), se mete como score peso 0,20 e invertido (sub-score medio 76, nunca <50 → +5,2 pts cuasi-constantes).
- **Impacto:** explica direccionalmente la mayoría del alfa negativo (C1 −27,55 € / C2 −6.018,82 €). La atribución €-exacta por factor **no es cuantificable** sin backtest A/B (muestra de 8-14 cierres) → ver hipótesis. La normalización de pesos sí es correcta (recompute = score almacenado al 4º decimal) — **no es la causa**.

### CR-2 — Trailing stop demasiado ajustado para baja volatilidad (EJECUCIÓN) · CAUSA RAÍZ · confianza ALTA

ATR×2,5 sobre un ETF calmo da una distancia minúscula; un retroceso normal de 1,5-2,5% liquida posiciones que el benchmark buy&hold no sufre.

- **Código:** `backend/trading/stops.py:94-107` (`stop_distance = atr×STOP_ATR_MULTIPLE`), `backend/scheduler/jobs.py:622-643` (protective_sell cada 15 min en market hours). `.env STOP_ATR_MULTIPLE=2.5`.
- **Datos:** distancia de stop derivada SPY 2,10%, VTI 2,20%, QQQ 3,46% vs AMD 12,40%. % vs avg_cost al disparar el 06-05: SPY **−1,54%**, VTI **−1,69%**, QQQ **−2,53%**. `job_runs` 06-05: VIX 16-19 (muy bajo VIX_TIGHTEN_ABOVE=30, panic_hold=false) → régimen calmo no mitigó; los stops saltaron por ruido intradía normal.
- **Impacto (C1):** stops low-vol evitables SPY+VTI+QQQ = **−2,07 €**; cluster high-vol AMD+AVGO+TSLA = **−18,89 €** (mezcla selección + cristalización en el suelo local del 06-05). En C2 es el patrón espejo ~199×.

### CR-3 — Asimetría de salida sin cooldown → whipsaw (ARQUITECTURA) · CAUSA RAÍZ · confianza ALTA

El protective_sell es la única vía de venta real; el scorer-exit (umbral 45) nunca dispara porque el RSI alto sigue puntuando BUY mientras el precio cae. El job diario está cebado para recomprar el nombre que el stop acaba de vender.

- **Código:** `backend/analysis/scoring/composite_scorer.py:64-65` (SELL solo si score ≤ min_score_to_exit=45). `grep cooldown|blacklist|recently_sold|do_not_rebuy backend/` = **0 coincidencias** (no existe guard de recompra). Recompra en `backend/trading/portfolio_manager.py:89-97`.
- **Datos:** `algorithm_signals` AMD se mantuvo BUY todo el episodio (86,4 → 61,2; mínimo 61,2, nunca ≤45). Round-trip AMD C2: SELL 06-05 @466,15 → BUY 06-08 @466,85 (+0,15% más caro). En C1 el rebuy fue −1,26% (más barato) pero igualmente reabre riesgo en el nombre stopeado.
- **Impacto:** 1 round-trip estéril confirmado (AMD): realizar −11,67 € (C1) / −2.815,96 € (C2) y reabrir riesgo. A 10 días el churn es bajo pero escalará; con broker real cada round-trip pagaría comisión (hoy no modelada).

### SÍNTOMAS (no causas) — confirmados pero no explican el alfa negativo

| Hallazgo | Estado | Detalle |
|---|---|---|
| **Caja 49,3%** | síntoma estructural | `backend/trading/risk_manager.py:109,123,125`: MAX_POSITION_PCT 0,05 × MAX_OPEN_POSITIONS 10 = 50% desplegable + MIN_CASH_PCT 0,20. La caja no sangra; limita la recuperación. No causa el alfa negativo. |
| **Benchmark stale/no-idempotente** | bug de datos | `portfolio_manager.py:166-184` + `market_queries.py:44-54` (get_close_asof arrastra staleness). NULL 5 días (05-29..06-02); 06-04==06-05 pese a SPY −2,6%. Sobre-estimó el under-performance del 06-05 en **2.205,17 € ≈ 2,21 pp**. El alfa **total** acumulado (~−5,5/−6 pp) sí es válido; solo la atribución día-a-día queda sesgada. |
| **`unrealized_pnl` fantasma** | bug de datos | `portfolio_positions` arrastra 7 filas qty=0 con upnl stale (~−2.300 € de doble cómputo en C2). KPI de latente sin filtrar `qty>0` está inflado ~40%. |
| **Data-freshness gap** | proceso | 06-08 (lunes) operó 7 compras con cierre del 06-05 (3 días). Fill = close_0605×1,001. € directo 0 (señal y fill comparten bar stale); riesgo real en broker live. |
| **Validación advisory-only** | robustez | `backend/data_ingestion/ingest.py:133-144` nunca consume `report.ok`. 0 anomalías >50% en ventana → 0 € impacto; riesgo latente. |
| **Sin modelo de comisiones** | riesgo Phase 2 | `grep commission\|fee\|brokerage backend/` = 0. 0 € hoy; amplificaría el coste del whipsaw en real. |

### Refutado / corregido en verificación

- **"7 posiciones vaciadas el 06-05":** falso, fueron 5 (las 8 ventas se reparten 06-02..06-05).
- **"Rebote +3,2% el 06-06":** no reproducible (06-06 es fin de semana, sin barra SPY; el bench baja).
- **"14 posiciones abiertas, 1/14 ganador":** mezcla cerradas (qty=0) con abiertas; el libro real es 7 abiertas, 0 ganadoras (hit-rate 0/7).
- **"Anclaje benchmark inconsistente 751,17 vs 759,34":** artefacto de cálculo; con SPY_start=756,48 toda la serie se explica. El defecto es staleness del numerador, no no-determinismo.
- **"close vs adj_close, 0 ex-div en ventana":** hubo 4 filas ex-div (MCD×2, NVDA, TLT); impacto 0 € porque esos símbolos no se operaron, no por ausencia de ex-div.

---

## Qué se hizo y por qué

- **El sistema construyó solo 3 indicadores técnicos (RSI/MA/ATR)** y no las señales núcleo del diseño (momentum cross-seccional, clasificador de régimen, multiplicador macro), que siguen como stubs observation-only. **Por qué:** Phase 4 implementó la *estructura* del scorer según el contrato del Software Architect; la *dirección económica* de las señales quedó sin calibrar y contradice `00-signal-synthesis.md`. La matemática de pesos es correcta; el defecto es de calibración/semántica.
- **Se eligieron entradas en techos locales** (RSI alto + extensión + alta vol). **Por qué:** RSI entra crudo con peso 0,50 (passthrough), ma_trend premia la distancia sobre la media y el ATR inyecta un floor de score. El diseño nunca pidió RSI por nivel alto como compra.
- **Se vendió todo por trailing stop, nunca por el scorer.** **Por qué:** el scorer-exit (umbral 45) es inalcanzable para nombres comprados con RSI alto; el protective_sell ATR×2,5 quedó como única válvula y, demasiado ajustado, liquidó ruido normal en cascada el 06-05.
- **Se recompró AMD al día siguiente del stop.** **Por qué:** no existe cooldown/blacklist post-stop; los dos jobs trabajan en sentidos opuestos.
- **Quedó ~50% en caja.** **Por qué:** es el cap estructural de exposición (5%×10 + 20% mínimo de caja), por diseño, no un bug.

---

## Handoff notes

**Qué produje:** descomposición del P&L de ambas carteras (realizado/latente, por símbolo, sector y tipo de operación) reconciliada al céntimo contra la caja; métricas de rendimiento reales; jerarquía causa-raíz vs síntoma con evidencia SQL/file:línea, impacto en €/pp y confianza, integrando los veredictos adversarios de las 6 áreas.

**Lo que el siguiente agente necesita saber:**
- Las **tres causas raíz** (selección del scorer, stop demasiado ajustado, asimetría de salida sin cooldown) son independientes y deben corregirse en orden: **primero el scorer** (la causa de mayor peso), luego stops y cooldown. Subir exposición (caja) **antes** de arreglar el scorer amplificaría las pérdidas.
- Toda corrección debe ir vía `config/strategy.yaml` / `.env` (nada hardcodeado) y **respetar el seam BrokerAdapter** (`portfolio_id` sigue siendo argumento de constructor, no de `place_order`).
- Dos bugs de datos colaterales a sanear para que el reporting sea fiable: `unrealized_pnl` en filas qty=0 y `benchmark_value` stale/no-idempotente.

**Decisiones diferidas / hipótesis no verificadas (requieren backtest del Experiment Tracker):**
- Atribución €-exacta de cada señal (RSI/MA/ATR) al alfa negativo: no aislable con 8-14 cierres; colinealidad RSI↔ma_trend.
- Contrafactual "mantener AMD vs stop+recompra" y coste recurrente del whipsaw a futuro.
- Coste de oportunidad de la caja ociosa (contrafactual "capital totalmente invertido").
- Que el RSI corregido (mean-reversion/regime-conditioned) mejore el PnL en este universo: plausible, pendiente de forward-test. **No aplicar cambios de trading aún** — esto es diagnóstico + plan.
