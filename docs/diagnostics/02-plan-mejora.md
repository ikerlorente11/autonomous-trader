<!-- Agent: Investment Researcher | Phase: diagnóstico | Depends on: workflow diagnostico-perdidas -->

# Plan de mejora — Autonomous Trader (corrección del sangrado de alfa)

> **Estado de implementación (rama `feat/per-portfolio-strategy-version`, 2026-06-08):**
> - **P1 — hecho, como variante de estrategia (A/B), no global.** En vez de cambiar
>   `strategy.yaml` para todos, ATR→0 vive en `config/strategies/v2.yaml` (overlay). El base
>   (`strategy.yaml`, "v1") mantiene `atr: 0.20`. Cada cartera elige su versión (`strategy_label`)
>   y el motor la opera con esa config; v1 vs v2 se compara por rendimiento de cartera.
> - **P8 — hecho.** `paper_broker._apply_sell` pone `unrealized_pnl=0` al quedar la posición plana
>   (qty≤0). La app ya filtraba `qty != 0` (NAV/equity eran correctos); esto sanea la columna cruda.
>   Backfill de filas existentes pendiente al desplegar: `UPDATE portfolio_positions SET unrealized_pnl=0 WHERE qty=0;`
> - **P9 — DIFERIDO (no es one-liner).** Investigado: el NAV se sella a las 08:15 UTC con la barra
>   del día hábil *anterior* (la del día aún no existe), y se marca también en fines de semana.
>   Un check ingenuo de staleness anularía el benchmark a diario. Requiere decidir el *sellado del
>   snapshot* (fecha de la barra, o no snapshotear sin sesión) — fuera de este lote seguro.
>
> Sin cambios aplicados a `main` ni desplegados.

> **Autor:** Quinn (Investment Researcher), con el Experiment Tracker para la medición.
> **Estado:** plan accionable. **No aplica ningún cambio de trading** (CLAUDE.md: este encargo es diagnóstico + plan; la ejecución se aprueba aparte).
> **Restricciones honradas:** paper-only, `BrokerAdapter` intacto (`PortfolioManager` nunca toca un broker concreto), **nada hardcodeado** (todo peso/umbral/parámetro vive en `config/strategy.yaml` o env).
> **Documento previo:** `docs/diagnostics/01-diagnostico-perdidas.md`.

---

## 0. Tesis del diagnóstico (lo que hay que arreglar, en una frase cada uno)

Las dos carteras pierden **-8,06% (C1, 459,69 €)** y **-8,57% (C2, 91.430,05 €)** vs un benchmark SPY rebasado de **-2,50%**: **alfa -5,5 a -6,1 pp** — el grueso de la pérdida es **selección/ejecución, no beta**. Las causas raíz **confirmadas** son:

1. **El scorer compra caro / vende barato por construcción** (señal mal dirigida): RSI passthrough crudo peso **0,50** (BUY a RSI medio 66,6; 38% de los BUY con RSI≥70), `ma_trend` premia la **extensión** sobre la media (BUY ma_trend 69 vs SELL 28), y el **ATR está dentro del score** peso 0,20 e **invertido** (más volatilidad → más score; sub-score nunca <50, +5 pts cuasi-constantes). `corr(composite,RSI)=0,963`, `corr(composite,ma_trend)=0,975`. **[AI Engineer + Investment Researcher, confirmada]**
2. **El stop trailing es demasiado ajustado y dispara en ruido normal**: ATR×2,5 cortó SPY/VTI/QQQ a **-1,5/-1,7/-2,5%** (régimen VIX 16-19, sin tighten). **74% del realizado de C2 (-3.728 €) se cristalizó en un solo día (06-05)** con 5 stops, 3 de ellos ETFs de índice amplio (caída de mercado, no idiosincrásica). **[Backend Architect + FP&A, confirmada]**
3. **Whipsaw sin anti-churn**: el `protective_sell` vende y el job diario **recompra el mismo nombre** porque sigue puntuando BUY (AMD: stop 06-05 → recompra 06-08 ~igual/más caro; round-trip realizó **-2.816 € en C2 / -11,67 € en C1**). No existe ningún guard de recompra (`grep cooldown|blacklist|recently_sold` = 0). **[Backend Architect + FP&A, confirmada]**
4. **Concentración por acumulación al alza**: el scorer compró AMD **4 veces** (518→522→543→543), ~22.500 € (≈41% del equity desplegado al pico), justo antes de la caída. Sin tope de adds ni de peso por nombre. **[FP&A, comportamiento confirmado; % de atribución incierto pero importes en € correctos]**

**Síntomas (no causas) / a no priorizar como pérdida:** el **~49,3% en caja** es estructural (`MAX_POSITION_PCT 0,05 × MAX_OPEN_POSITIONS 10 = 50%` + `MIN_CASH_PCT 0,20`) — coste de oportunidad, no sangrado. **Bugs de reporting/datos:** `unrealized_pnl` stale en filas `qty=0` (sobre-reporta latente ~2.300 € en C2), `benchmark_value` NULL 5/11 días y stale-1 sesión (06-05 sobre-estimó el bench **2.205 € ≈ 2,21 pp** ese día), marks de fin de semana. Comisiones **no modeladas** (riesgo futuro al swap a real).

---

## 1. Cambios priorizados por **impacto esperado × esfuerzo**

Orden = mayor (impacto/esfuerzo) primero. "Impacto" es sobre el **alfa forward** salvo que se indique reporting/robustez.

| # | Cambio | Causa raíz | Impacto esperado | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| **P1** | **Sacar el ATR del score** (`weights.atr → 0`, renormaliza solo) | RC1 (ATR-en-score) | Alto (quita +5 pts cuasi-constantes y el tilt a volatilidad) | **Muy bajo** (1 línea YAML) | 🔴 Inmediato |
| **P2** | **Cooldown anti-recompra post-stop** (`STOP_REENTRY_COOLDOWN_DAYS`) | RC3 (whipsaw) | Alto (elimina round-trips estériles; AMD habría evitado recristalizar) | Medio | 🔴 Alto |
| **P3** | **Piso mínimo de distancia de stop** (`STOP_MIN_DISTANCE_PCT`) | RC2 (stop ajustado) | Alto (evita stops de ruido en ETFs calmos; ~2 €/C1 directos + captura de rebotes) | **Bajo** | 🔴 Alto |
| **P4** | **RSI regime-conditioned / mean-reversion** (sub-score premia sobreventa, no sobrecompra) | RC1 (RSI passthrough) — **la de mayor peso, 0,50** | **Muy alto** (invierte el sesgo compra-caro) | Medio-Alto | 🟠 Alto (tras P1) |
| **P5** | **`ma_trend` → trend gate saturado** (no premiar cuánto está por encima) | RC1 (extensión) | Medio-Alto (quita refuerzo de entradas tardías) | Bajo | 🟠 Medio |
| **P6** | **Tope de adds y de peso por símbolo** (`MAX_ADDS_PER_SYMBOL`, `MAX_WEIGHT_PER_SYMBOL`) | RC4 (concentración) | Medio-Alto (AMD: de -3.486 € a ~-870 €, ahorro ~2,6 pp) | Medio | 🟠 Medio |
| **P7** | **Rank-normalización cross-seccional** de sub-scores (synthesis §3.4) | RC1 (gate absoluto sesgado) | Medio (gate 60/45 relativo al universo) | Medio | 🟡 Medio |
| **P8** | **Fix reporting `unrealized_pnl` en filas `qty=0`** | bug datos | Bajo (P&L, no €) pero crítico para medir | Bajo | 🟡 Medio |
| **P9** | **Benchmark idempotente + no marcar fin de semana** | bug datos | Bajo (métrica), habilita atribución día-a-día | Medio | 🟡 Medio |
| **P10** | **Modelo de comisiones en PaperBroker** (`COMMISSION_PCT`/`PER_ORDER`) | honestidad backtest | Bajo hoy (0 €), alto para Phase 2 y para penalizar churn | Bajo | 🟢 Bajo |
| **P11** | **Activar momentum cross-sectional real + multiplicador macro** (synthesis §3.1/§3.2) | RC1 (núcleo del diseño ausente) | Muy alto estructural | **Alto** | 🟢 Roadmap |
| **P12** | **Gating de frescura de datos** antes de decidir/ejecutar | calidad decisión | Bajo hoy (0 €), alto en broker real | Bajo | 🟢 Bajo |

> **Secuencia recomendada de despliegue (una variable por experimento, ver §3):** P1 → P3 → P2 → P4 → P5/P6/P7 → P11. Las correcciones de reporting (P8/P9) van **antes** de medir cualquier A/B porque hoy el latente está inflado y el benchmark sesgado.

---

## 2. Cambios concretos (diffs/pasos propuestos — **no aplicados**)

> **Nota de arquitectura (clave):** `backend/analysis/config.py` valida con pydantic `extra="forbid"`. **Toda clave nueva en `strategy.yaml` requiere añadir el campo correspondiente al modelo pydantic** (`RankerConfig`/`ScoringConfig`/`RsiParams`/…) o el arranque falla. Los parámetros de **trading** (stops, sizing, cooldown) viven en **env** (los lee `os.environ` en `stops.py`/`risk_manager.py`), no en `strategy.yaml`; ahí basta documentarlos en `.env.example`. Esto mantiene "nada hardcodeado" y respeta el seam.

### P1 — Sacar el ATR del score (impacto alto, coste 1 línea)

**Por qué:** el diseño maestro reserva el ATR para **sizing/stops**, no como atractivo (`docs/research/00-signal-synthesis.md:27,125`). Hoy `volatility.py:44-54` hace el sub-score monótono creciente con la volatilidad → premia los nombres más ruidosos (peores drawdowns) e inyecta un floor de +5 pts. La normalización del scorer ya renormaliza sobre las señales presentes (`composite_scorer.py:42-55`), así que poner el peso a 0 lo elimina del composite **sin tocar código**.

```diff
# config/strategy.yaml
   weights:
-    rsi: 0.50
-    ma_trend: 0.30
-    atr: 0.20
+    rsi: 0.50
+    ma_trend: 0.30
+    atr: 0.0      # ATR sale del score → solo sizing/stops (synthesis §1, §3.1)
```

> El indicador ATR se sigue computando (lo consumen `stops.py` y el sizing); solo deja de puntuar. `config_hash` cambiará → nueva `strategy_version` automática (medible en A/B).

### P4 — RSI regime-conditioned / mean-reversion (la corrección de mayor peso)

**Por qué:** `momentum.py:31-35` no sobrescribe `latest_score`, así que `base.py:44-49` pasa el RSI **crudo** (clip 0-100): RSI alto → score alto → compra sobrecompra. Verificado: BUY a RSI medio 66,6 (38% ≥70), SELL a RSI 36. El diseño nunca usa RSI por nivel alto como compra (`synthesis:44,137-145`: `rsi_oversold 0,35` en reversión, `rsi_bb 0,10` en momentum).

**Mínimo viable (sin clasificador de régimen, configurable):** dar al RSI un `latest_score` que mapee según un **modo** y los umbrales `overbought/oversold` ya presentes en config. Modo `mean_reversion` ⇒ sub-score alto cuando RSI bajo.

```python
# backend/analysis/indicators/momentum.py  (añadir override de latest_score)
# Nuevo parámetro `mode` inyectado desde config (passthrough | mean_reversion | banded)
    def latest_score(self, df: DataFrame) -> float | None:
        finite = self.compute(df).dropna()
        if finite.empty:
            return None
        rsi = clip_0_100(float(finite.iloc[-1]))
        if self.mode == "mean_reversion":
            return 100.0 - rsi            # sobreventa puntúa alto
        if self.mode == "banded":
            # alto cerca de oversold, bajo cerca de overbought, plano en medio
            ...
        return rsi                        # passthrough (comportamiento actual)
```

```diff
# config/strategy.yaml
   rsi:
     period: 14
     overbought: 70.0
     oversold: 30.0
+    mode: mean_reversion   # passthrough | mean_reversion | banded
```

```diff
# backend/analysis/config.py  (REQUERIDO por extra="forbid")
 class RsiParams(_Frozen):
     period: int
     overbought: float
     oversold: float
+    mode: Literal["passthrough", "mean_reversion", "banded"] = "passthrough"
```

> El engine (`engine.py:47-60`) debe pasar `mode` al construir `RelativeStrengthIndex`. **Confianza: media** sobre la dirección correcta para ESTE universo/horizonte → **obligatorio forward-test (§3) antes de fijar `mean_reversion`**; arrancar A/B contra `passthrough`.

### P5 — `ma_trend` como puerta de tendencia saturada

**Por qué:** `moving_average.py:39-51` devuelve `logistic(sensitivity·distance)`, creciente con la extensión (BUY ma_trend 69). El diseño lo quiere como **trend gate** (`synthesis:58`), no como puntuación creciente con la distancia.

```diff
# backend/analysis/indicators/moving_average.py  (saturar la extensión)
-        distance = last_close / last_ma - 1.0
-        return logistic_0_100(self._sensitivity * distance)
+        distance = last_close / last_ma - 1.0
+        # Puerta de tendencia: elegible si precio>MA, sin premiar CUÁNTO por encima.
+        capped = min(distance, self._cap) if distance > 0 else distance
+        return logistic_0_100(self._sensitivity * capped)
```

```diff
# config/strategy.yaml + MaTrendParams en config.py
   ma_trend:
     kind: ema
     period: 20
     sensitivity: 20.0
+    extension_cap: 0.02   # satura el "cuánto por encima" en +2%
```

Alternativa de bajo coste sin tocar código: bajar `weights.ma_trend` (p.ej. a 0,15) y subir `rsi` tras corregir su dirección.

### P3 — Piso mínimo de distancia de stop (env, sin tocar config YAML)

**Por qué:** `stops.py:103-107` usa `atr_multiple·atr`; en ETFs calmos eso es ~1,5-2,5% → ruido. Un piso desacopla la distancia de la volatilidad mínima del nombre.

```diff
# backend/trading/stops.py  (en stop_distance)
     if atr is not None and atr_multiple is not None and atr_multiple > 0:
         base = atr_multiple * atr
     else:
         base = peak * pct
-    return base * distance_factor
+    floor = peak * _min_distance_pct()      # nuevo _decimal_env("STOP_MIN_DISTANCE_PCT", 0)
+    return max(base, floor) * distance_factor
```

`.env.example`: `STOP_MIN_DISTANCE_PCT=0.05` (5%; default 0 = comportamiento actual). **El seam no cambia** (sigue siendo aritmética pura). Alternativa: subir `STOP_ATR_MULTIPLE` de 2,5 a ~4.

### P2 — Cooldown anti-recompra post-stop

**Por qué:** rompe el bucle `protective_sell ↔ execute_paper_trades`. Hoy no hay guard alguno.

**Pasos (sin romper el seam — es filtro de candidatos, no del broker):**
1. Nueva query en `backend/db/queries/portfolio_queries.py`: símbolos con un `trade_orders` `side='sell'` y `strategy_version='protective-sell'` dentro de `N` días para un `portfolio_id`.
2. En `execute_paper_trades` (`jobs.py:456-471`), filtrar `ranked` por portfolio quitando esos símbolos **antes** de `manager.execute_signals(ranked)`.
3. Parámetro env `STOP_REENTRY_COOLDOWN_DAYS` (default 0 = off). Leído en el job, no hardcodeado.

> Nota: el cooldown es **por portfolio** (cada cartera puede tener historiales distintos). No toca `place_order` ni el `BrokerAdapter`.

### P6 — Tope de adds / peso por símbolo

**Por qué:** AMD 4 adds al alza = ~41% del equity desplegado. La concentración convirtió un nombre malo en catástrofe.

**Pasos:** en `risk_manager.py:120-141` (`size_positions`), añadir guardas configurables por env: `MAX_ADDS_PER_SYMBOL`, `MAX_WEIGHT_PER_SYMBOL`. El `RiskManager` ya recibe `open_position_count`; se le puede pasar también el `{symbol: peso_actual}` y `{symbol: nº_compras}` para vetar adds. Defaults permisivos (= comportamiento actual) para que sea opt-in.

### P7 — Rank-normalización cross-seccional

**Por qué:** `synthesis §3.4` exige normalizar cada sub-score a percentil del universo antes de ponderar; hoy son absolutos y sesgados (ATR medio 76). El `composite_scorer` opera símbolo-a-símbolo (sin acceso al universo), así que la rank-norm debe ir **una capa antes**, en `engine.py`, sobre el conjunto de `IndicatorResult` del día. Flag `scoring.rank_normalize: true` (+ campo en `ScoringConfig`).

### P8 — Reporting `unrealized_pnl` en filas `qty=0`

**Por qué:** `portfolio_positions` arrastra filas cerradas con `unrealized_pnl` stale (sobre-reporta latente C2 ~2.300 €). Cualquier KPI que sume latente sin `WHERE qty>0` está inflado. **Fix:** en `portfolio_manager.py` (`update_positions`/snapshot) poner `unrealized_pnl=0` cuando `qty=0`, o filtrar `qty>0` en los queries de reporting.

### P9 — Benchmark idempotente

**Por qué:** `_benchmark_value` (`portfolio_manager.py:166-184`) usa `get_close_asof(SPY, asof)` (`market_queries.py:44-54`), que arrastra staleness (06-04==06-05; NULL 5/11 días; marks de domingo). **Fix:** anclar `SPY_start` a la primera barra real ≥ `first_nav.ts`; **no escribir** `benchmark_value` si falta barra SPY del día (en vez de heredar); no marcar NAV en días sin sesión. Opcional: recomputar la serie histórica.

### P10 — Comisiones en PaperBroker

`paper_broker.py:place_order`: deducir `COMMISSION_PCT`/`COMMISSION_PER_ORDER` del cash, reflejado en el ledger. Sigue siendo detalle del **adapter** (seam intacto). Hace visible el coste del churn en el experiment-framework.

---

## 3. Cómo se medirá la mejora (define el experimento — Experiment Tracker)

> Framework: `backend/experiments/` (`tracker.py`, `comparator.py`) + `docs/finance/experiment-framework.md`. Cada edición de `strategy.yaml` genera una **`strategy_version` distinta** (`config_hash`), que ya queda registrada en `trade_orders.strategy_version` y `algorithm_signals` — esa es la unidad de A/B.

### 3.1 Métrica objetivo (primaria)
- **Alfa diario medio vs SPY rebasado** (`ret_cartera − ret_benchmark`), agregado a alfa acumulado del periodo de test.
- **Secundarias:** max drawdown sobre total, profit factor de round-trips, hit-rate de salidas, nº de stops disparados a <3% de avg_cost (proxy de "ruido"), nº de round-trips de whipsaw (sell→rebuy mismo nombre en ≤N días), Sharpe diario.
- **Pre-requisito:** desplegar P8 y P9 primero, para que alfa y latente sean fiables.

### 3.2 Diseño del experimento (forward-test reproducible)
- **Tipo:** paper forward-test A/B por `strategy_version`. **No** hay backtest histórico fiable con sólo 10 días y datos OHLCV stale; el sistema ya es un harness de paper-trading, así que el A/B forward es la vía honesta.
- **Aislar una variable por experimento** (no mezclar P1+P4 en la misma corrida; el diagnóstico mostró colinealidad RSI/MA/ATR — cambios simultáneos no se pueden atribuir).
- **Control vs tratamiento:** dos `strategy_version` corriendo en paralelo sobre **el mismo universo y el mismo día**. Mecanismo limpio sin tocar el seam: usar dos portfolios espejo (la infra ya soporta multi-portfolio; el `BrokerAdapter` recibe `portfolio_id` en el constructor) — uno con la config actual, otro con la nueva vía `STRATEGY__*` env override por proceso, o registrar señales de ambas versiones y comparar las decisiones que **habrían** tomado (`comparator.py`).
- **Horizonte mínimo:** ≥ 20 sesiones de trading por brazo (el diagnóstico avisa: 10 obs no son estadísticamente robustas; Sharpe/vol fueron "direccionales"). Pre-registrar el horizonte y el universo.

### 3.3 Criterio de éxito (pre-registrado, falsificable)
- **Éxito P1+P4+P5 (señal):** el brazo tratamiento muestra **alfa acumulado ≥ +3 pp** sobre el control en ≥20 sesiones, **y** RSI medio de los BUY cae de ~66 a **<50** (prueba directa de que ya no compra sobrecompra), **y** profit factor de round-trips > control.
- **Éxito P2+P3 (ejecución):** **0 round-trips de whipsaw** en la ventana, **y** reducción ≥50% de stops disparados a <3% de avg_cost, **sin** empeorar el max drawdown.
- **Éxito P6 (concentración):** ningún símbolo supera `MAX_WEIGHT_PER_SYMBOL`; la peor pérdida individual ≤ 1,2× del tamaño de un lote.
- **Thesis breaker (revertir):** si el tratamiento **no** mejora el alfa tras 20 sesiones, o empeora el drawdown >2 pp, **revertir** la `strategy_version` y reabrir hipótesis (anti-anchoring: no mantener un cambio por estar comprometido con él).

### 3.4 Reproducibilidad
- Toda config queda serializada en `experiment_runs.config` (`config.py:model_dump()`); el `config_hash` la sella. Re-correr = mismo env + mismo universo seed (`config/watchlist.seed.csv`).

---

## 4. Riesgos y qué NO tocar

**Riesgos de los cambios propuestos:**
- **P4 (RSI mean-reversion) es una hipótesis, no una certeza.** El diagnóstico confirma que la dirección **actual** es económicamente incoherente, pero que `mean_reversion` rinda mejor en este universo/horizonte está **sin probar contra-factualmente**. Por eso va **gated por forward-test** y con default `passthrough`.
- **Subir exposición (la "caja 49%") amplificaría pérdidas si el scorer sigue comprando caro.** **NO** tocar `MAX_POSITION_PCT`/`MAX_OPEN_POSITIONS`/`MIN_CASH_PCT` hasta que P1/P4/P5 estén validados. La caja no sangra; es síntoma.
- **Stop demasiado ancho (P3) reduce protección a la baja.** Calibrar el piso con A/B; un piso excesivo deja correr pérdidas reales (AMD/AVGO/TSLA fueron caídas verdaderas, no solo ruido).
- **Cooldown (P2) puede impedir reentradas legítimas.** Empezar con `N` pequeño (p.ej. 3 días) y medir el coste de oportunidad.
- **Atribución €-exacta por señal sigue sin ser aislable** sin el A/B; no prometer cifras de recuperación como hechos — son hipótesis cuantificadas.

**Qué NO tocar (innegociable, CLAUDE.md):**
- **No bypassear `BrokerAdapter`.** Cooldown, sizing y comisiones se implementan como **filtro de candidatos / lógica del adapter**, nunca llamando a un broker concreto desde `PortfolioManager`. `qty` sigue siendo `Decimal`.
- **Nada hardcodeado.** Todo nuevo parámetro va a `config/strategy.yaml` (con su campo pydantic) o a env documentada en `.env.example`. Recordar `extra="forbid"`: clave YAML nueva ⇒ campo en el modelo.
- **No implementar broker real** (Phase 2 fuera de alcance). Las comisiones se modelan en el **PaperBroker**.
- **No tocar el watchlist a mano** (API/seed); sin auth/multiusuario.
- **Respetar el presupuesto de RAM de la Pi.** Rank-normalización cross-seccional (P7) y momentum (P11) deben operar sobre el universo en memoria sin inflar el pico de análisis (<400 MB).
- **No aplicar ningún cambio de trading en este encargo.** Es diagnóstico + plan.

---

## Handoff notes

**Qué produje:** plan de mejora priorizado por impacto×esfuerzo (P1-P12), con diffs/pasos concretos para `config/strategy.yaml`, `backend/analysis/indicators/{momentum,moving_average,volatility}.py`, `backend/analysis/config.py`, `backend/trading/{stops,risk_manager,portfolio_manager,paper_broker}.py` y `backend/scheduler/jobs.py` — **ninguno aplicado**. Diseño de experimento A/B forward-test con métrica objetivo (alfa vs benchmark), criterios de éxito pre-registrados y thesis breakers.

**Lo que el siguiente agente necesita saber:**
- **Quick win sin código:** P1 (`weights.atr → 0`) es una sola línea y el scorer renormaliza solo (`composite_scorer.py:42-55`). Genera nueva `strategy_version` automáticamente → A/B inmediato.
- **Trampa de config:** `backend/analysis/config.py` usa pydantic `extra="forbid"`. Cualquier clave nueva en `strategy.yaml` **debe** añadirse al modelo pydantic o el arranque rompe. Los parámetros de trading (stops/sizing/cooldown/comisiones) van en **env** (`os.environ` en `stops.py`/`risk_manager.py`), no en el YAML.
- **Orden de despliegue:** P8/P9 (fixes de reporting/benchmark) **antes** de medir nada; luego una variable por experimento (P1 → P3 → P2 → P4 → …). No mezclar por colinealidad RSI/MA/ATR.
- **Seam intacto:** cooldown y sizing son filtros de candidatos; comisiones son detalle del PaperBroker. `place_order` no cambia de firma.

**Decisiones diferidas / preguntas abiertas:**
- Calibración exacta de `STOP_MIN_DISTANCE_PCT`, `STOP_REENTRY_COOLDOWN_DAYS`, `MAX_WEIGHT_PER_SYMBOL`, `extension_cap` y `rsi.mode` → la fija el Experiment Tracker con el forward-test (≥20 sesiones), no este documento.
- ¿`mean_reversion` puro o `banded`/`regime-conditioned`? Empezar con A/B `mean_reversion` vs `passthrough`; el régimen por símbolo (P11) es la versión completa del diseño (`synthesis §3.1`).
- Recomputar o no la serie histórica de `benchmark_value` (P9): decisión de Data Engineer; no afecta al alfa total acumulado, sí a la atribución día-a-día.
