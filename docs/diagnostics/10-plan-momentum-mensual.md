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

## 6. Riesgos conocidos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Momentum crash (reversión violenta post-pánico) | `market_filter` SMA200 corta entradas en bajista + stops ATR intradía; el criterio §4.4.3 lo mide |
| Historia corta (12-1 puntuable solo desde ~2024-05; ventanas de ~6-12 meses) | Asumido y declarado: tres ventanas es lo que hay; la OOS es pequeña — por eso el criterio es exceso > 0, no significancia estadística (esa se exigirá en vivo, doc 09 §3.1) |
| Sesgo de la watchlist (62 nombres líquidos, sin quebrados = sesgo de supervivencia leve) | Igual para todas las versiones comparadas; se anota en el resultado |
| `_SLICE_BARS=280` deja solo 28 barras de margen sobre el 12-1 | Restricción documentada §2.1; ampliarla es cambio global, diferido |

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
