<!-- Prompt de orquestación | Objetivo: diagnosticar la rentabilidad -8% y proponer plan de mejora -->

# Prompt — Revisión de pérdidas y plan de mejora del autónomo trader

> Copia todo lo que hay debajo de la línea como prompt. Está pensado para ejecutarse
> en este repositorio (la Pi) con los agentes instalados en `.claude/agents/`.
> Convierte hipótesis en conclusiones **solo** tras verificarlas contra datos y código.

---

## Contexto

Sistema de paper-trading autónomo (ver `CLAUDE.md` — es la constitución del proyecto y
**manda sobre todo**). Lleva ~10 días operando (desde 2026-05-29) y acumula una
**rentabilidad de ≈ -8%**, mientras que el **benchmark cae solo ≈ -2,5%**: la estrategia
pierde unos **5,5 puntos porcentuales frente al mercado** — no es solo beta de mercado,
hay sangrado de alfa que hay que explicar.

Quiero que el equipo de agentes **estudie el estado actual de las transacciones, explique
en detalle qué se ha hecho, por qué, y por qué se ha perdido tanto**, y entregue un
**plan de mejora priorizado y accionable**.

## Snapshot real (medido en DB el 2026-06-08, punto de partida — verifícalo y amplíalo)

| Cartera | Capital aportado | NAV total | Rent. | Benchmark | Cash | Equity | Posiciones | PnL no realizado |
|---|---|---|---|---|---|---|---|---|
| 1 — Cartera 500 | 500,00 € | 459,69 € | **-8,06%** | 487,24 € (-2,55%) | 226,78 € | 232,91 € | 14 | -28,83 € |
| 2 — Cartera 100K | 100 000 € | 91 430,05 € | **-8,57%** | 97 448,87 € (-2,55%) | 45 049,13 € | 46 380,91 € | 14 | -5 855,13 € |

- **31 operaciones** por cartera (23 compras / 8 ventas), 14 símbolos, 2026-05-29 → 2026-06-08.
- `strategy_version` presentes: `0.1.0+597824`, `0.1.0+74ca3c`, y `protective-sell` (16 ops).
- Solo señales **técnicas** activas (RSI/MA/ATR). Las señales macro/news/fundamentales se
  acaban de activar hoy pero son **observation-only** (no alimentan al scorer todavía).
- Pesos del scorer (`config/strategy.yaml`): `rsi: 0.50`, `ma_trend: 0.30`, `atr: 0.20`.
  `min_score_to_act: 60`, `min_score_to_exit: 45`.

## Hipótesis a verificar (NO son conclusiones — confírmalas o descártalas con evidencia)

1. **El RSI es passthrough con peso 0,50**: el sub-score = valor crudo de RSI, así que un RSI
   alto (sobrecompra, 70+) produce score alto → el sistema **compra lo sobrecomprado** y
   **vende lo sobrevendido**. Posible compra-caro/vende-barato sistemático. ¿Es así? ¿Cuánto
   pesa en las pérdidas?
2. **`ma_trend` premia la extensión sobre la media** (logística de % por encima de la MA) →
   refuerza comprar nombres ya estirados. ¿Coincide con los peores trades?
3. **Churn / whipsaw**: hay round-trips (AMD vendido 06-05 y recomprado 06-08; QQQ comprado y
   vendido el mismo día). ¿El `protective_sell` (trailing stop) liquida y luego el job diario
   vuelve a comprar el mismo nombre? Cuantifica coste por whipsaw y comisiones/slippage modelados.
4. **Sizing y diversificación**: 14 posiciones con fracciones. ¿`RiskManager`/`MIN_POSITION_EUR`/
   `MAX_OPEN_POSITIONS` generan sobre-concentración o lastre de caja? (¿por qué ~50% en cash?)
5. **Timing de ejecución**: las compras se llenan a precio de cierre (`paper fill`). ¿Hay sesgo
   de entrada (comprar el cierre del día de señal) que empeora el resultado?
6. **Stop trailing demasiado ajustado**: ¿`STOP_ATR_MULTIPLE`/`TRAILING_STOP_PCT` y el régimen
   por VIX están cortando ganadores en ruido normal?
7. **¿El benchmark es comparable?** Verifica cómo se calcula `benchmark_value` y si la
   comparación es justa (mismo periodo, mismas aportaciones).

## Equipo de agentes a usar (instalados en `.claude/agents/`)

Orquesta en paralelo donde sea independiente; sintetiza al final. Roles sugeridos:

- **Financial Analyst** — métricas de rendimiento reales: Sharpe, max drawdown, CAGR, alfa vs
  benchmark, calmar, hit-rate, profit factor, PnL realizado vs no realizado. Cuantifica *cuánto*
  de la pérdida es realizado, no realizado, comisiones/slippage, y beta vs alfa.
- **FP&A Analyst** — descomposición del P&L: atribución por símbolo, sector, día y por tipo de
  operación (entradas del scorer vs ventas de `protective_sell`). Qué trades concretos sangraron.
- **Investment Researcher** — calidad de la lógica de señales y del scoring: ¿la dirección del
  RSI/MA es correcta? ¿el composite tiene sentido económico? Propón corrección de señales.
- **AI Engineer** — auditoría del motor de análisis/scoring (`backend/analysis/`): mapea
  `config/strategy.yaml` → código real, confirma cómo se calcula cada sub-score y el composite,
  y si el ranking hace lo que dice la doc (`docs/research/00-signal-synthesis.md`).
- **Backend Architect** — auditoría de `backend/trading/` (`portfolio_manager`, `paper_broker`,
  `risk_manager`, `stops.py`) y del job `execute_paper_trades` + `protective_sell`: sizing,
  idempotencia, whipsaw, modelo de comisiones/slippage. **Respeta el seam `BrokerAdapter`.**
- **Experiment Tracker** — diseña cómo medir si los cambios propuestos mejoran (A/B de versiones
  del scorer, backtest/forward-test reproducible, qué `strategy_version` ganó). Usa
  `backend/experiments/` y `docs/finance/experiment-framework.md`.
- **Data Engineer** — valida la **calidad de los datos** que alimentaron las decisiones (barras
  OHLCV: huecos, splits/dividendos, precios erróneos). Una pérdida puede venir de datos malos.
- **Test Results Analyzer / Reality Checker** — verificación adversaria: refuta cada conclusión
  antes de aceptarla; confirma que las cifras del diagnóstico reproducen contra la DB.

## Dónde están los datos y el código (puntos de entrada)

- DB (TimescaleDB) en contenedor `trader-db`, base `autonomous_trader`. Tablas clave:
  `trade_orders`, `portfolio_nav`, `portfolio_positions`, `cash_movements`, `portfolios`,
  `signal_values`, `algorithm_signals`, `macro_series`, `news_sentiment`, `fundamentals_quarterly`.
  Consulta:
  `docker exec trader-db psql -U trader -d autonomous_trader -c "<SQL>"`
- Estrategia y pesos: `config/strategy.yaml` (todo parametrizado, nada hardcodeado).
- Motor: `backend/analysis/` (scoring, ranking, indicadores).
- Trading: `backend/trading/` (`portfolio_manager.py`, `paper_broker.py`, `risk_manager.py`,
  `stops.py`); jobs en `backend/scheduler/jobs.py`.
- Diseño previo: `docs/research/00-signal-synthesis.md`, `docs/finance/performance-metrics.md`,
  `docs/architecture/protective-sell.md`.

## Restricciones (de `CLAUDE.md` — innegociables)

- Phase 1: **solo simulación**, sin dinero real. No implementar llamadas a broker real.
- **No bypassear `BrokerAdapter`** — `PortfolioManager` nunca toca un broker concreto.
- **Nada hardcodeado**: todo peso/umbral/parámetro va en `config/strategy.yaml` o env.
- No tocar el watchlist a mano (se gestiona por API/seed), sin auth/multiusuario.
- Cumplir presupuesto de RAM de la Pi (ver `CLAUDE.md`).

## Entregables exigidos

1. **`docs/diagnostics/01-diagnostico-perdidas.md`** — diagnóstico detallado:
   - Resumen ejecutivo (qué pasó y por qué, en 10 líneas).
   - Métricas de rendimiento reales (tabla) y atribución del P&L (por símbolo/sector/tipo de op).
   - Causas raíz **verificadas** (cada una con evidencia: SQL, líneas de código `file:línea`,
     ejemplos de trades). Distingue causa-raíz de síntoma.
   - Qué se hizo y por qué (decisiones del scorer/stops que llevaron a cada pérdida).
2. **`docs/diagnostics/02-plan-mejora.md`** — plan priorizado:
   - Lista de cambios ordenados por impacto esperado × esfuerzo, con el *porqué*.
   - Cambios concretos de `config/strategy.yaml` y/o código (con diffs propuestos o pasos).
   - Cómo se medirá la mejora (métrica objetivo, forward-test, criterio de éxito) — define el
     experimento con el Experiment Tracker antes de aplicar nada.
   - Riesgos y qué NO tocar.
3. Cada documento empieza con el comentario de cabecera de agente que exige `CLAUDE.md` y
   termina con `## Handoff notes`.

## Reglas de calidad

- No afirmes una causa sin reproducirla contra datos/código. Marca lo no verificado como hipótesis.
- Cuantifica siempre que puedas (€ y %). "Perdió por X" debe venir con cuánto atribuye X.
- No apliques cambios de trading todavía: este encargo es **diagnóstico + plan**. La ejecución
  de los cambios se aprueba aparte.
