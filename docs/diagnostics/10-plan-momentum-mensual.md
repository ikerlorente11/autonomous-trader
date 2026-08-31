<!-- Agent: SoftwareArchitect | Phase: post-5 | Depends on: 07-plan-v7-v8, 09-igualacion-carteras, 00-signal-synthesis -->

# Plan v11 — momentum cross-seccional a cadencia mensual (diseño, solo backtest)

**Estado: diseño pre-registrado. No se implementa cartera viva ni se toca la flota hasta el
fin de la moratoria (2027-03) y el veredicto del cohorte igualado (doc 09).** Este documento
fija la estrategia, los dos knobs que faltan en el código y el protocolo de calibración
ANTES de mirar ningún resultado — la lección de v10 (07-plan §11) y la regla del doc 09 §3.

## 1. Por qué esta familia y no otra iteración más

Tras 10 versiones diarias en 3,5 meses ninguna bate a SPY con significancia. Las lecciones
acumuladas apuntan todas en la misma dirección:

- **La fricción y la ejecución dominan la señal** a frecuencia diaria (v1 en vivo: la mayor
  parte del −11,6% era ejecución, no señal — 07-plan §3; m1: 93% de la pérdida fue fricción).
- **El único edge robusto y accesible a este stack** (datos diarios gratuitos, sin intradía
  fiable, sin fundamentales de pago) es el momentum/trend cross-seccional a horizonte
  mensual: el factor individual mejor documentado académicamente (synthesis §3.1;
  Jegadeesh & Titman 1993, el UMD de Fama-French), explotable con barras diarias y
  rotación baja.
- **Las piezas ya existen**: `PriceMomentum(period, skip)`, `rank_normalize` (percentil
  cross-seccional), `market_filter` (gate de régimen), stops ATR anchos (v7),
  `vol_target_pct` (s1, testeado y apagado). v11 es composición, no desarrollo nuevo —
  salvo dos knobs (§3).

Lo que la cadencia mensual compra: ~12 decisiones de entrada/salida por señal al año en vez
de ~250, es decir, una fracción del coste por churn que se comió a m1 y castigó a v1.

## 2. La estrategia

| Pieza | Decisión | Ya existe |
|---|---|---|
| Universo | La watchlist en runtime (hoy 62 símbolos, barras desde 2023-04). Nada hardcodeado. | Sí |
| Señal | `momentum` (retorno sobre `period` barras terminando `skip` barras atrás), **único peso** (`momentum: 1.0`, resto 0.0) | Sí |
| Selección | `rank_normalize: true` → el composite ES el percentil de momentum en el universo del día; top-N vía `min_score_to_act` = 100·(1−N/U) | Sí |
| Cadencia | **Mensual**: entradas Y salidas por señal solo el primer día de sesión de cada mes; el resto de días BUY/SELL→HOLD | **No — knob §3.1** |
| Stops | Protectores intradía SIN cambios (`protective_sell` cada 15 min): ATR×3,5, suelo 7% (el perfil v7 — coherente con mantener semanas) | Sí |
| Sizing | Equal-weight 1/N (recomendado, §2.3); vol-target como eje del sweep | Parcial — knob §3.2 |
| Gate de mercado | `market_filter` base (SPY vs SMA200) intacto: en tendencia bajista el rebalanceo mensual no abre entradas nuevas (sí permite salidas) | Sí |

### 2.1 Señal: period/skip

- **`skip: 21`** (≈1 mes): excluye el mes más reciente, donde domina la reversión de corto
  plazo — es la convención "12-1" de toda la literatura y ya es el default del
  `MomentumParams` existente.
- **`period`**: el clásico 12-1 es retorno de t−252 a t−21 → `period: 231`. El base trae
  126/21 (6-1). **Ambos entran en el sweep** (§4.2); no se decide aquí.
- **Restricción dura del código**: la señal necesita `period + skip + 1` barras. El
  backtester corta en `_SLICE_BARS = 280` y la ventana viva de análisis (~400 días
  naturales) da ~276 sesiones → **231+21=252 cabe; lookbacks mayores NO** sin ampliar
  ambas ventanas de datos (diferido, ver Handoff).
- **`sensitivity` no se barre**: bajo `rank_normalize` la squash logística es monótona,
  así que el percentil es idéntico para cualquier valor — un parámetro menos, gratis.

### 2.2 Selección y histéresis

Con U=62: `min_score_to_act = 87` ≈ top-8; `= 92` ≈ top-5 (eje del sweep).
`min_score_to_exit: 50` **fijo, no barrido**: un nombre entra en el top-N pero solo sale
por señal cuando cae bajo la mediana del universo — la banda ancha es lo que mantiene la
rotación baja (el mecanismo de histéresis ya existente en el ranker, synthesis §4.2).

### 2.3 Sizing: equal-weight, con vol-target como contraste

**Recomendación: equal-weight 1/N** (fixed-fractional con techo por posición ≈ (1−reserva)/N).
Razones: es el estándar de la literatura (los retornos documentados del factor son de
carteras equal-weight), no añade parámetros, y s1 (07-plan §4) demostró que el vol-target
recorta justo lo que una señal de reversión explota — pero dejó escrito que sobre una base
momentum podría ayudar (los crashes de momentum son de alta volatilidad). Por eso
**con/sin `vol_target_pct: 0.004` es un eje del sweep**, no el default.

### 2.4 Overlay tentativo (`config/strategies/v11.yaml` — se crea al implementar, ninguna cartera lo selecciona)

```yaml
ranker:
  min_score_to_act: 87.0      # top-8 de 62 ≈ percentil 87 (eje del sweep: 92 = top-5)
  min_score_to_exit: 50.0     # histéresis: sale por señal solo bajo la mediana
  rebalance_cadence: monthly  # knob nuevo (§3.1)
scoring:
  weights: { rsi: 0.0, ma_trend: 0.0, atr: 0.0, momentum: 1.0 }
  rank_normalize: true
indicators:
  momentum: { period: 231, skip: 21 }   # 12-1 (eje del sweep: 126 = 6-1)
trading:
  stop_atr_multiple: 3.5      # stops v7: anchos, para horizonte de semanas
  stop_min_distance_pct: 0.07
  allow_pyramiding: false
  stop_reentry_cooldown_days: 3
  max_position_pct: 0.11      # knob nuevo (§3.2): ≈ (1 − 0.05) / 8
  min_cash_pct: 0.05          # knob nuevo (§3.2)
  max_open_positions: 8       # knob nuevo (§3.2)
```

El `market_filter` (SPY/SMA200) se hereda del base sin tocarlo.

## 3. Qué le falta al código (dos knobs, todo opcional, `None` = comportamiento actual intacto)

### 3.1 Cadencia de rebalanceo: `ranker.rebalance_cadence`

**Knob**: `RankerConfig.rebalance_cadence: Literal["monthly"] | None = None` — junto a
`market_filter`, que es su gemelo conceptual (ambos son gates de ACCIÓN por día, no de
ejecución por cartera).

**Semántica**: en `DefaultAnalysisEngine.score_universe`, tras puntuar, si la cadencia está
activa y hoy NO es día de rebalanceo → `BUY→HOLD` y `SELL→HOLD` (con `reason` anotado, como
hace ya el market_filter). Los stops protectores no pasan por aquí, así que siguen intradía.

**"Día de rebalanceo", sin estado y sin calendario bursátil**:
`month(asof) != month(max última fecha de barra del universo)`. Las señales se calculan
sobre barras hasta d−1 y se ejecutan al open de d (convención viva desde 2026-08-31, la
misma del backtester): si la última barra es la última sesión del mes anterior, d es la
primera sesión del mes → rebalanceo. Idéntico en vivo y en backtest porque la información
(el mapping de barras + `asof`) es la misma en ambos. Caso degradado: tras un apagón con
barras rancias el gate podría disparar un día tardío del cruce de mes — aceptable, y el
gate P12 (`MAX_BAR_STALENESS_DAYS=3`) ya excluye datos rancios antes.

**Por qué NO en `TradingConfig` (alternativa considerada y descartada)**: un
`trading.rebalance_sessions` consumido por `_execution_config` exigiría el cambio pareado
en dos rutas de ejecución (jobs en vivo + bucle del backtester — riesgo de divergencia, el
pecado que P7 corrigió centralizando en `score_universe`), y "N sesiones desde el último
rebalanceo" necesita estado persistido; "primer día de sesión del mes" es puro y stateless.
Además dejaría `run_analysis` persistiendo señales con acciones que la ejecución ignora.

**Captura por el backtester: automática, cero casos especiales** — `runner.py` llama a
`score_universe(slices, asof)` con barras hasta d−1 y `asof=d`, exactamente la información
que el gate necesita. Los días no-rebalanceo el engine emite HOLDs, el bucle no compra ni
vende por señal, y el paso 3 (stop diario aproximado) sigue funcionando. En vivo,
`execute_paper_trades` corre a diario como siempre y simplemente no encuentra acciones;
el guard de idempotencia no cambia.

### 3.2 Envolvente de sizing por versión: `trading.{max_position_pct, min_cash_pct, max_open_positions}`

**El hueco**: hoy son env globales (`MAX_POSITION_PCT=0.05`, `MIN_CASH_PCT=0.20`,
`MAX_OPEN_POSITIONS=10`) → exposición máxima estructural ≈ 50%. Un top-8 mensual necesita
~12% por nombre; con el techo global al 5% la estrategia queda condenada a ~40% invertido
y no puede batir a SPY por construcción. (Nota honesta: este techo pesa sobre TODAS las
versiones actuales — puede ser parte del "nadie bate a SPY". Se anota, no se toca ahora.)

**Knob**: tres campos nuevos en `TradingConfig`, patrón idéntico a los existentes —
`max_position_pct: float | None = None`, `min_cash_pct: float | None = None`,
`max_open_positions: int | None = None`; `None` = fallback al env (byte-a-byte igual para
base y v1-v10, cuyo hash de config solo cambia si se les añade la clave — no se les añade).

**Coste de implementación mínimo**: `FixedFractionalRiskManager.__init__` YA acepta los
tres como argumentos opcionales con fallback a env — solo hay que plumbearlos en los dos
puntos de construcción (jobs `_execution_config` → PortfolioManager, y
`backtest/runner.py` donde ya se plumbea `vol_target_pct`). Cambio pareado pequeño y
simétrico; el patrón existe.

**Lo que NO se toca**: el seam `BrokerAdapter` (nada de esto se acerca a `place_order`;
`qty` sigue `Decimal`), el esquema de DB, los overlays v1-v10, `strategy.yaml` base (los
campos nuevos son opcionales con default None — el base no los declara), y ningún valor
hardcodeado (todo en overlay/env).

## 4. Protocolo de calibración pre-registrado (regla de v10: 2 ventanas de calibración + 1 OOS jamás usada para elegir)

### 4.1 Ventanas (disjuntas; barras desde 2023-04, el 12-1 necesita ~252 barras → primer día puntuable ≈ 2024-05)

| Ventana | Fechas | Papel | Carácter |
|---|---|---|---|
| **C1** | 2024-06-03 → 2025-05-30 | Calibración | Tendencia (el tramo fuerte de SPY) |
| **OOS** | 2025-06-02 → 2025-12-31 | **Validación — se corre UNA vez, solo la ganadora del sweep** | Mixto |
| **C2** | 2026-01-02 → 2026-07-31 | Calibración | Incluye el lateral de 2026 que hundió a v1 |

C1 y C2 abarcan los dos regímenes conocidos; la OOS queda en medio y no se mira hasta
haber elegido. Comando: el flujo estándar del backtester
(`python -m backend.backtest --labels v11,... --start/--end`), comisiones y slippage
globales activos como en todo backtest desde 2026-07-21.

### 4.2 Sweep permitido (8 combinaciones, nada más)

| Eje | Valores |
|---|---|
| N (→ `min_score_to_act`, `max_open_positions`, `max_position_pct`≈0.95/N) | 5, 8 |
| Lookback (`momentum.period`, `skip` fijo 21) | 126 (6-1), 231 (12-1) |
| Sizing | equal-weight, `vol_target_pct: 0.004` |

Fijos y NO barridos: `min_score_to_exit: 50`, stops v7, cooldown 3d, `skip 21`,
`market_filter` base. Ampliar el sweep tras ver resultados invalida el protocolo.

### 4.3 Regla de selección en C1+C2 (antes de tocar la OOS)

Elegible: rotación < 2×/año en AMBAS ventanas **y** ≥ 4 rebalanceos con operaciones por
ventana (una candidata que "gana no jugando" — la lección de c1 en 07-plan §2 — no es
elegible). Entre las elegibles gana el **mayor Sharpe medio de las dos ventanas**; empate
→ menor maxDD medio. Una sola ganadora pasa a la OOS.

**Definición de rotación** (fija por adelantado): nocional total vendido (señal + stops)
÷ NAV medio de la ventana ÷ años de la ventana. < 2×/año.

### 4.4 Criterios de promoción a "candidata aprobada" (escritos antes de mirar la OOS)

Todos a la vez, sobre la única pasada OOS de la ganadora:

1. **Exceso sobre SPY > 0** (retorno total de la ventana OOS).
2. **Rotación < 2×/año** también en la OOS.
3. **maxDD ≤ maxDD de SPY en la misma ventana + 5 pp**.
4. Operó: ≥ 3 rebalanceos con operaciones.

Si falla cualquiera: v11 se archiva con resultado negativo documentado (como v9, s1) y
**no hay segunda ronda de sweep contra la misma OOS** — la OOS quemada no se reutiliza.

### 4.5 Aprobada ≠ viva

Pasar §4.4 solo otorga el estado "candidata aprobada para lanzamiento". El lanzamiento
real exige ADEMÁS: fin de la moratoria (2027-03), veredicto del cohorte igualado
(doc 09 §3), y entonces carteras nuevas 500 €/100k € con el reloj del experimento a cero.
El backtest calibra; **la decisión de vivir se toma con las reglas del doc 09** — la
lección de v1 no se repite.

## 5. Qué NO hace este plan

- **No toca carteras vivas** ni la flota (v1, v3, v7, v8, v10, m3 siguen intactas).
- **No crea cartera nueva** hasta fin de moratoria + veredicto del cohorte.
- **Sin pesos fundamentales, macro multiplier ni sentimiento** — una variable por
  experimento: v11 es momentum puro. Combinarlo con régimen/fundamentales sería una v12+.
- **No cambia base, overlays existentes, envs globales, esquema de DB ni el seam
  `BrokerAdapter`.** Los dos knobs de §3 son opcionales con default None.
- **No implementa nada todavía** — este es el diseño; la implementación (gate + plumbing
  de sizing + overlay + tests) es un PR aparte cuando se decida ejecutar el protocolo.
  *(Actualización 2026-08-31: implementado y ejecutado — resultados en §7; los knobs son
  genéricos y quedan mergeados aunque v11 se archive.)*

## 6. Riesgos conocidos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Momentum crash (reversión violenta post-pánico) | `market_filter` SMA200 corta entradas en bajista + stops ATR intradía; el criterio §4.4.3 lo mide |
| Historia corta (12-1 puntuable solo desde ~2024-05; ventanas de ~6-12 meses) | Asumido y declarado: tres ventanas es lo que hay; la OOS es pequeña — por eso el criterio es exceso > 0, no significancia estadística (esa se exigirá en vivo, doc 09 §3.1) |
| Sesgo de la watchlist (62 nombres líquidos, sin quebrados = sesgo de supervivencia leve) | Igual para todas las versiones comparadas; se anota en el resultado |
| `_SLICE_BARS=280` deja solo 28 barras de margen sobre el 12-1 | Restricción documentada §2.1; ampliarla es cambio global, diferido |

## 7. Resultados de calibración (2026-08-31) — v11 NO pasa; la OOS queda sin quemar

El protocolo §4 se ejecutó tal como estaba escrito (implementación: gate de cadencia +
envolvente de sizing + `scripts/backtest_sweep_v11.py`; comisiones 0,05% y slippage 0,1%
activos). Tablas completas de las 8 combinaciones, sin selección previa:

**C1 (2024-06-03 → 2025-05-30, tendencia; SPY +11,67%)**

| combo | retorno | Sharpe | maxDD | rot/año | mesesSig | trades | stops |
|---|--:|--:|--:|--:|--:|--:|--:|
| n5_l126_ew | −11,72% | −0,83 | −20,93% | 5,64 | 10 | 58 | 29 |
| n5_l126_vt | −1,16% | −1,50 | −4,28% | 1,38 | 10 | 66 | 32 |
| n5_l231_ew | −11,19% | −0,80 | −17,98% | 5,44 | 9 | 56 | 28 |
| n5_l231_vt | −0,46% | −1,29 | −3,54% | 1,18 | 10 | 62 | 31 |
| n8_l126_ew | −8,57% | −0,67 | −19,77% | 5,98 | 10 | 98 | 48 |
| n8_l126_vt | −0,17% | −0,76 | −6,17% | 2,12 | 10 | 100 | 49 |
| n8_l231_ew | −8,38% | −0,71 | −18,57% | 5,46 | 10 | 90 | 45 |
| n8_l231_vt | +0,68% | −0,66 | −5,51% | 2,01 | 10 | 98 | 49 |

**C2 (2026-01-02 → 2026-07-31, lateral+recuperación; SPY +9,35%)**

| combo | retorno | Sharpe | maxDD | rot/año | mesesSig | trades | stops |
|---|--:|--:|--:|--:|--:|--:|--:|
| n5_l126_ew | −8,84% | −0,85 | −15,18% | 4,83 | 6 | 31 | 15 |
| n5_l126_vt | −1,66% | −1,85 | −3,25% | 0,99 | 6 | 38 | 18 |
| n5_l231_ew | −2,64% | −0,19 | −14,32% | 6,13 | 6 | 38 | 19 |
| n5_l231_vt | +0,55% | −0,81 | −2,28% | 1,11 | 6 | 39 | 19 |
| n8_l126_ew | −13,19% | −1,46 | −17,34% | 5,64 | 6 | 59 | 27 |
| n8_l126_vt | −3,39% | −2,10 | −4,69% | 1,92 | 6 | 65 | 30 |
| n8_l231_ew | +2,07% | +0,06 | −9,93% | 5,29 | 6 | 54 | 26 |
| n8_l231_vt | +2,47% | −0,02 | −2,93% | 1,80 | 6 | 59 | 28 |

**Aplicación literal de §4.3.** Elegibles (rotación < 2×/año en AMBAS ventanas, ≥4
meses con operaciones): solo `n5_l126_vt` (1,38/0,99) y `n5_l231_vt` (1,18/1,11) — los
n8_vt fallan C1 por décimas (2,12/2,01) y TODAS las equal-weight rotan 5-6×/año.
Ganadora formal: `n5_l231_vt`, Sharpe medio −1,05.

**Decisión: v11 se archiva en calibración y la OOS NO se corre.** La ganadora formal
está a 10-12 pp de SPY en las dos ventanas de calibración; el criterio §4.4.1 (exceso
OOS > 0) no tiene ninguna posibilidad realista, y correr la OOS la quemaría para
siempre (§4.4: la OOS usada no se reutiliza). Preservar la ventana virgen para un
rediseño vale más que el trámite.

**Diagnóstico del mecanismo (por qué falla, no solo cuánto):**

1. **El stop intradía destruye la cadencia mensual.** ~50% de todas las operaciones son
   stops en las 16 celdas. El ciclo: compra fuerza el día 1 → el trailing (ATR×3,5,
   suelo 7%) salta con un retroceso ordinario a mitad de mes → cooldown 3d + cadencia
   impiden reentrar → recompra el mes siguiente más caro. Las equal-weight sangran
   −8/−13% por ese ciclo (y de ahí su rotación 5-6×, que las inelegibiliza); el
   momentum 12-1 de la literatura NO lleva trailing stop del 7% — retiene a través de
   retrocesos que aquí venden el mínimo local sistemáticamente.
2. **Las vol-target "aprueban" elegibilidad no jugando.** Con riesgo 0,4%/posición y
   stop ~10%, cada posición es ~4% del NAV → ~20% invertido. Son planas porque están
   en caja — la variante moderna de la lección c1 (07-plan §2): `mesesSig` no detecta
   infra-exposición. Un protocolo futuro debe añadir un mínimo de exposición media.
3. La comparación honesta ya existía: v10 captura momentum con confirmación de régimen
   y ejecución diaria (+44,8% en su ventana larga) — trocear ese mecanismo en
   rebalanceos mensuales con stops intradía es peor que ambas cosas por separado.

**Qué implicaría una v11b (protocolo NUEVO, la OOS sigue virgen):** exit solo en
rebalanceo (sin trailing intradía, o stop de catástrofe ≥20%), mínimo de exposición
media como criterio de elegibilidad, y quizá `max_position_pct` como tope duro con
equal-weight real. Requiere pre-registro nuevo ANTES de correr nada, y las mismas C1/C2
ya están contaminadas para elegir stops (se miraron): cualquier v11b debería calibrar
en ventanas desplazadas o aceptar la contaminación por escrito.

## Handoff notes

**Producido**: este documento — diseño completo de v11 (momentum cross-seccional mensual),
la especificación de los dos knobs de config que faltan, y el protocolo de calibración
pre-registrado (ventanas, sweep de 8, reglas de selección y promoción) ANTES de correr
ningún backtest.

**Lo que necesita el implementador (un PR, sin tocar nada más):**
1. `RankerConfig.rebalance_cadence: Literal["monthly"] | None = None` + el gate en
   `score_universe` (patrón market_filter: BUY/SELL→HOLD con reason; regla
   `month(asof) != month(última barra)`). Tests: día 1 de mes opera, resto no; fin de
   año; barras rancias.
2. `TradingConfig.max_position_pct / min_cash_pct / max_open_positions` (None=env) +
   plumbing en los dos constructores de `FixedFractionalRiskManager` (jobs y
   `backtest/runner.py` — donde ya viaja `vol_target_pct`). Test: overlay sin las claves
   ⇒ byte-a-byte igual que hoy (hashes de v1-v10 intactos).
3. `config/strategies/v11.yaml` según §2.4 (las 8 variantes del sweep se generan como
   overlays temporales o `STRATEGY__…` env en el contenedor de backtest — no se
   comitean 8 ficheros).
4. Correr §4 en el orden escrito y anexar los resultados A ESTE documento (C1+C2 primero,
   OOS una vez).

**Decisiones diferidas:**
- Ampliar `_SLICE_BARS`/ventana viva para lookbacks > 231 barras (cambio global, no lo
  necesita el sweep actual).
- Cadencias adicionales (`weekly`) — el Literal se amplía si algún experimento futuro lo
  pide; hoy solo `monthly`.
- El techo global de exposición (~50%) que pesa sobre TODAS las versiones vivas (§3.2,
  nota honesta) — merece su propio experimento, no se mezcla con este.
- v12+ (momentum + régimen/fundamentales) — solo si v11 pasa la OOS.
