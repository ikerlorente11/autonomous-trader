<!-- Agent: Claude (autonomous session) | Phase: post-5 diagnostics | Depends on: 04-plan-v4.md, 00-signal-synthesis.md -->

# v5 / v6 + backtester — activación completa de P11 y calibración por evidencia

Fecha: 2026-06-12 (misma sesión que cerró v4). Mandato del owner: «desarrolla del tirón todo lo
que puedas a día de hoy» — en vez de un brazo por mes, construir el harness que permite calibrar
versiones en minutos y lanzar todas las versiones defendibles a la vez.

## Qué se construyó

### 1. Backtester (`backend/backtest/`)
El cuello de botella del proyecto era la velocidad de aprendizaje: 1 día de evidencia por día de
calendario. El backtester reproduce el pipeline REAL — el mismo `DefaultAnalysisEngine.score_universe`
(indicadores, rank-normalización P7, multiplicador de régimen), el mismo `FixedFractionalRiskManager`,
la misma matemática de stops (`stops.stop_distance`) y los mismos knobs env de slippage/comisión —
sobre las barras almacenadas, día a día:

- señales con datos hasta d−1 (como el job de las 07:30), fills en el OPEN de d ± slippage;
- stop trailing aproximado con high/low diarios usando el pico del día ANTERIOR (sin look-ahead
  intradía), VIX histórico (FRED `VIXCLS`) para el régimen de stops;
- fundamentales con lag de disponibilidad de 45 días sobre `period_end` (anti look-ahead);
- régimen macro recomputado por día desde `macro_series` (histórico FRED desde 2024-03).

CLI: `python -m backend.backtest --labels v1,...,v6 --start ... --end ... [--json out]`
(en contenedor desechable; léelo en `backend/backtest/__main__.py`). Float, no Decimal: es un
simulador para ordenar versiones, no un ledger; las diferencias documentadas son idénticas para
todas las versiones → la comparación es justa.

**Limitaciones conscientes:** sin `news_buzz` (no hay histórico de noticias — la señal se cae y
los pesos renormalizan, igual que en vivo cuando falta un dato); fills al open vs el fill paper
en vivo al close de d−1; el stop intradía es una aproximación con barras diarias.

### 2. Universo 28 → 62 símbolos + 3 años de barras
Añadidos 34 valores líquidos diversificados (financieras, salud, energía, industriales, consumo,
tech/comms, IWM/EFA) vía API — el watchlist sigue siendo dato en runtime, nada hardcodeado.
`scripts/backfill_bars.py` (idempotente) rellenó barras desde 2023-04 (49k filas). El momentum
cross-seccional necesita amplitud; 28 nombres eran pocos.

### 3. Plumbing P11 completo (engine/jobs)
- `score_universe(bars, asof, extra_signals=, regime_score=)`: señales no-bar (fundamentales,
  news) entran al compuesto SOLO si la versión las pondera; el multiplicador de régimen
  (`scoring.regime_multiplier`, lineal floor→ceil sobre el score 0–100) escala el compuesto antes
  de los umbrales. Base/v1–v4: byte-a-byte sin cambios.
- `jobs._universe_extras()`: una sola computación por día alimenta la persistencia en observación
  (igual que antes), el scoring de cada versión y el multiplicador. Solo lecturas de BD.
- Bug real arreglado por el camino: `acceleration_score` desbordaba `math.exp` con bases YoY
  diminutas (visto con datos reales 2024); logistic numéricamente estable también en
  `indicators/base.logistic_0_100`.

### 4. Versiones nuevas (cadena de deltas — cada comparación aísla UNA variable)
- **v5 = v4 + multiplicador macro** (`regime_multiplier: floor 0.75 / ceil 1.05`): con estrés
  (curva invertida, VIX alto, spreads anchos) todo score se amortigua hasta −25% → menos nombres
  cruzan el umbral 60 → el sistema se repliega; risk-on apenas toca nada (+5% máx).
- **v6 = v5 + fundamentales** (`quality 0.15, revenue_accel 0.10, earnings_accel 0.10`):
  activa las señales que llevaban semanas en modo observación. Sin datos fundamentales un símbolo
  se puntúa con el resto (renormalización, nunca imputación).

## Calibración (resultados del backtest) — THESIS-BREAKER

Ventana 2024-09-02 → 2026-06-11 (~440 sesiones), 100k, costes por defecto (slippage 0.1%,
comisión 0), 62 símbolos. Benchmark SPY buy-and-hold: **+33.63%**.

| ver | return | CAGR | Sharpe | maxDD | trades | stops | win% | alpha vs SPY |
|-----|-------:|-----:|-------:|------:|-------:|------:|-----:|-------------:|
| **v1** | **+52.20%** | **+26.80%** | **1.01** | −21.22% | 751 | 220 | 31.7 | **+18.56%** |
| v2 |  −0.08% |  −0.04% | −16.74 |  −0.25% |   4 |   2 | 50.0 | −33.71% |
| v3 |  +6.73% |  +3.75% |  −0.06 |  −6.47% | 747 | 245 | 44.2 | −26.90% |
| v4 | +18.99% | +10.33% |  +0.58 | −10.32% | 625 | 268 | 41.9 | −14.64% |
| v5 | +14.84% |  +8.14% |  +0.39 |  −9.95% | 619 | 268 | 41.3 | −18.79% |
| v6 | +13.98% |  +7.68% |  +0.36 |  −9.78% | 616 | 270 | 44.2 | −19.65% |

**El resultado invalida la línea de mejora v2→v6.** v1 (el "control" que comprábamos fuerza y
considerábamos defectuoso) es **el mejor con diferencia** y el **único que bate a SPY** (+18.6 pp
de alfa, Sharpe 1.01 — el mejor también en riesgo-ajustado, no solo en retorno). v2–v6 quedan muy
por debajo de v1 **y** de SPY.

**Por qué (el sesgo que cometimos):** el diagnóstico de v2–v6 nació de **~10 sesiones en vivo**
(mayo–junio 2026), un tramo de corrección donde v1 perdía ~5%. Optimizamos contra esa muestra
diminuta y no representativa. Sobre 21 meses, la ventana está dominada por una tendencia alcista
(SPY +33%), y **todos los "arreglos" son defensivos/contrarios** y reducen sistemáticamente la
participación en esa tendencia:
- v3 (rank-normalización + RSI contrario): el peor de los que operan (+6.7%, Sharpe ≈0). Comprar
  caídas y normalizar por percentil **mata el seguimiento de tendencia** que daba el edge.
- v4 (= v3 + momentum): recupera mucho (+19%, Sharpe 0.58) — **el momentum es la única señal que
  claramente ayuda**, confirmando synthesis §3.1. Es el mejor de la familia "disciplinada".
- v5 (= v4 + régimen) y v6 (= v5 + fundamentales): cada capa defensiva **resta** un poco más en
  esta ventana alcista. Es coherente con su diseño: amortiguan exposición, lo que cuesta en un
  bull market y *debería* proteger en una caída — exactamente lo que el forward-test debe dirimir.

**Decisión calibrada (anti-anchoring, honesta con los datos):**
1. **v1 deja de ser solo "baseline": es el favorito según la evidencia.** Su debilidad real es el
   drawdown (−21%, ~2× el resto) y su dependencia de régimen (sufrió en la corrección de mayo).
2. **v4 es el mejor compromiso** retorno/riesgo de la familia con stops disciplinados (Sharpe 0.58,
   maxDD −10%): la mitad de drawdown que v1 a cambio de menos retorno.
3. **v2 se retira** (4 trades en 21 meses = caja; no aporta información). v3 queda como cola
   perdedora pero se mantiene vivo como ancla del experimento.
4. **No se mata ningún brazo por un solo backtest** (sería el mismo error que cometimos al vivo):
   v1/v4/v5/v6 corren en vivo en paralelo; ~20 sesiones forward deciden si el dominio de v1
   aguanta o era el régimen alcista. Pero el sesgo de partida queda **invertido**: la carga de la
   prueba ahora la tienen las versiones defensivas, no v1.

**Criterio pre-registrado forward:** una versión supera a otra si sube Sharpe sin empeorar maxDD
> 2 pp sobre ≥20 sesiones reales. Si v1 mantiene su ventaja, se promociona a default.

## Cómo se mide en vivo
- Brazos v1/v4/v5/v6 con carteras 500 € y 100k € cada uno; `/compare` para la alfa. (v1/v4 ya
  estaban; esta sesión añade v5/v6 para que las 6 versiones corran en paralelo.)
- ≥20 sesiones por brazo antes de cualquier veredicto; las significancias del comparator
  (bootstrap + Jobson-Korkie) están implementadas — falta el plumbing `compare()`.
- El backtest favorece a v1; el forward-test debe confirmar si aguanta fuera de un régimen alcista.

## Deuda y siguientes pasos (cuándo volver a evolucionar)
1. **~20 sesiones de vivo (mediados de julio 2026):** primer veredicto v4 vs v5 vs v6 con datos
   reales; retirar brazos perdedores, promover el ganador a default.
2. **Backtester fase 2:** walk-forward por tramos, grids de pesos (el CLI ya acepta cualquier
   overlay), métricas de rotación/exposición; carga de barras >3 años si hace falta.
3. **v7 candidato:** sizing con objetivo de volatilidad + límite de correlación entre posiciones
   (hoy 6 posiciones pueden ser la misma apuesta tech).
4. Deuda heredada de 04: retornos ajustados por flujos en `/performance`, comisiones en
   round-trips, plumbing del comparator.

## Handoff notes
- **Qué produje:** backtester + loader + CLI, plumbing P11 completo, v5/v6, universo 62 + 3 años
  de barras, fix overflow logistic, tests (engine extras, scorer multiplier, backtester puro,
  versiones), /info ES/EN con v5/v6.
- **Para el siguiente agente:** el backtest es la puerta de entrada de cualquier cambio de
  estrategia — nada se promociona a vivo sin pasar por él; respetar la cadena de deltas.
