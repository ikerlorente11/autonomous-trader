<!-- Agent: Claude | Phase: post-Phase-5 iteration | Depends on: 03-plan-v3.md, 04-plan-v4.md, 05-plan-v5-v6.md, 06-plan-filtro-mercado.md -->

# Plan v7 / v8 — iteración tras la primera revisión de resultados en vivo (2026-07-21)

## 1. Qué dijeron los datos en vivo (ventana común 2026-06-15 → 2026-07-21, SPY −1,69%)

| Versión | Retorno | Lectura |
|---|---|---|
| v3 | **+0,17%** | Única rentable; ~+1,9pp de alfa |
| v5 | −2,2% | Multiplicador de régimen ≈ sin efecto vs v4 |
| v4 | −2,2% | El momentum restó en lateral |
| v6 | −2,9% | **Experimento inválido**: Finnhub 429 congeló fundamentales (10-may) y noticias (12-jun) |
| v1 | **−11,6%** | La peor en vivo — y la mejor del backtest largo 2024-25 |
| v2 | 0% | No opera (baseline de caja, esperado) |
| micro m1 | **≈ −8,5% real** | Cifras del dashboard contaminadas por el bug de venta fantasma (reparado); la señal 5m es ~cero ANTES de costes: ~26 round-trips/día × ~0,2–0,3% de coste = la pérdida es fricción |

**Validación del backtester**: sobre la misma ventana reproduce el ranking en vivo
(v3 mejor, v1 peor, v4/v5/v6 en medio). La "contradicción" con el backtest largo
donde v1 ganaba es **dependencia de régimen**, no un fallo del backtester: v1
(umbral absoluto) gana en tendencia; v3 (rank relativo) gana en lateral.

## 2. Candidatas de una variable sobre v3 (backtest, ventana lateral 06-15→07-21)

| Candidata | Delta | Retorno | Stops | Win% | Lectura |
|---|---|---|---|---|---|
| c1 | gate 60→70 | −0,04% | 0 | — | 1 trade: gana "no jugando" — descartada como estrategia, pero confirma que el gate controla la exposición |
| c2 | market_filter MA100 | −0,72% | 13 | 18,8 | Idéntica a v3: el filtro no saltó (SPY sobre su MA100 toda la ventana) |
| c3 | regime mult. floor 0,55 | −2,22% | 14 | 17,6 | El régimen macro NO discrimina este lateral — empeora |
| **c4** | **stops ATR×3,5, floor 7%** | **−0,90%** | **7** | **36,4** | Retorno ≈ v3 con la mitad de stop-outs y el doble de win% — el perfil que buscamos |
| c5 | cooldown 7d | −1,44% | 14 | 27,8 | Empeora — el cooldown largo pierde re-entradas buenas |

Ventana larga multi-régimen (2024-09-02 → 2026-07-21): **[PENDIENTE — en ejecución]**.
Criterio de selección: la candidata debe **mejorar o igualar a v3 en la ventana
lateral Y en la larga**. v7 se lanza solo si sobrevive a ambas.

## 3. v8 — ensemble adaptativo al régimen (desarrollo nuevo)

El hallazgo más sólido de todo el A/B en vivo: **ninguna versión domina en ambos
regímenes**. v8 lo convierte en estrategia:

- `regime_switch` (nuevo en `StrategyConfig`): en días con el benchmark (SPY) al/sobre
  su MA100 el universo se puntúa con la config de `v1` (momentum/absoluta — la que ganó
  2024-25); por debajo, con la de `v3` (mean-reversion/relativa — la que gana el lateral
  2026). Las patas son los overlays existentes: una sola variable nueva (el conmutador).
- Los knobs de `trading` (stops, cooldown, no-pyramiding) NO se conmutan: pertenecen a
  v8 y mantienen el perfil protector de v3 en todo régimen.
- Fail-open a la pata defensiva (`chop`) si falta histórico del benchmark.
- Anidamiento prohibido (una pata no puede declarar su propio `regime_switch`).
- Vive dentro de `DefaultAnalysisEngine`, así que el backtester lo captura sin código
  aparte y `run_analysis`/`execute_paper_trades` no cambian.

**Resultado ventana lateral (06-15→07-21):** v8 −0,56% vs v3 −0,72% (maxDD −2,52 vs
−3,59; win% 38,5 vs 18,8). Hallazgo colateral importante: SPY estuvo sobre su MA100
los 24 días, así que v8 ejecutó **las señales de v1 con la disciplina de ejecución de
v3** (cooldown/floor/no-pyramiding, knobs propios de v8) — y esa combinación convierte
el −6,64% de v1 puro en −0,56%. La mayor parte de la pérdida de v1 en vivo era
**ejecución, no señal**.

## 4. s1 — sizing por volatilidad (equal-risk, desarrollo nuevo)

Hoy cada posición es un % fijo del valor (5%): un trade de un nombre volátil arriesga
3-4× más euros que uno tranquilo con el mismo stop ATR. Nuevo knob
`trading.vol_target_pct`: se arriesga ese % del valor por posición usando la distancia
del stop (ATR×múltiplo — el MISMO stop del protective-sell) como unidad de riesgo;
`MAX_POSITION_PCT` queda como techo de nocional. Se lanza solo si sobrevive a ambas
ventanas de backtest.

**Calibración:** con target 1% el techo del 5% ligaba para todo nombre con ATR < 8%
del precio — es decir, para todos: `s1` era byte-a-byte v3. Recalibrado a **0,4%**
(el techo liga bajo ATR ≈ 3,2% del precio: los tranquilos capan al 5%, los volátiles
reducen — reductor de riesgo, nunca apalancamiento). **Resultado ventana lateral:**
−1,17% vs v3 −0,72% (maxDD algo mejor). En lateral, encoger los volátiles encoge
también los rebotes que explota la mean-reversion. Pendiente la ventana larga; si no
la gana con claridad, s1 NO se lanza.

## 5. m3 — micro de baja frecuencia (desarrollo nuevo)

La atribución de costes del forward-test m1 (5 semanas) manda: señal ~cero bruta,
−8,5% neta. m3 ataca la fricción, no la señal:

- `trading.max_trades_per_day` (5): presupuesto de entradas por sesión — los jobs de
  intervalo re-puntúan todo el día y sin presupuesto el churn es ilimitado.
- `trading.min_hold_minutes` (60): una salida POR SEÑAL no cierra una posición más
  joven que la ventana (los scores 5m oscilan con ruido y cada round-trip paga spread).
  **Los stops protectores y el flatten EOD están exentos** — el riesgo nunca espera.
- `min_score_to_act 75`: entrar solo en los mejores rangos relativos.

Sin backtest intradía multi-régimen gratuito (limitación conocida), m3 se valida por
**forward-test contra m1 y m2** con la regla de decisión: si en 4 semanas ninguna
versión micro bate a caja neta de costes, la pista micro se apaga.

## 6. Atribución de costes (observabilidad)

`GET /api/portfolios/{id}/costs` (+ botón «Costes» en el panel de carteras): fills,
nocional comprado/vendido, flujo realizado, comisiones y slippage estimado — separa
"no hay edge" de "el edge se lo comen los costes" sin análisis manual. El slippage es
estimación con el `SLIPPAGE_PCT` vigente (los fills lo llevan embebido; el precio
pre-slippage no se almacena).

## 7. Cambios de flota propuestos

- **Lanzar**: v7 (= c4, si la ventana larga lo confirma), v8, s1 (ídem), m2 (el
  contraste que nunca arrancó), m3. Carteras de 500 € y 100k € por versión, como
  siempre.
- **Retirar**: v4 (redundante con v5 y ambas pierden; v5 se queda como test del
  multiplicador).
- **v6**: re-evaluar solo tras ≥4 semanas de fundamentales/noticias frescos post-fix
  del throttle de Finnhub.
- Comisiones (`COMMISSION_PCT=0.0005`) activadas globalmente el 2026-07-21 — todas las
  versiones pagan lo mismo; los retornos anteriores a esa fecha no las incluyen.

## 8. Medición

- Daily: NAV/alfa por cartera en `/compare` (p-valor), mismas reglas que v1-v6.
- Micro: m1 vs m2 vs m3 con la MISMA ventana forward y el endpoint de costes como
  segunda lectura (¿cae la fricción sin matar la señal?).
- Un experimento = una variable: v7 (stops), v8 (conmutador), s1 (sizing), m3 (freno
  de churn) son separables y comparables contra v3/m1 directamente.
