<!-- Agent: Claude (autonomous session) | Phase: post-5 diagnostics | Depends on: 03-plan-v3.md, 00-signal-synthesis.md -->

# v4 — momentum cross-seccional (P11 fase 1) + arreglos de broker

Fecha: 2026-06-12. Contexto de datos en ese momento (≈10 sesiones de v1, 4 de v3):

| Brazo | Capital aportado | NAV | P&L |
|---|---|---|---|
| v1-500 / v1-100k | 500 / 100 000 | 475,22 / 94 520,49 | **−4,96 % / −5,48 %** |
| v2-500 / v2-100k | 500 / 100 000 | 500,00 / 100 000,00 | 0 % — **0 órdenes desde su creación** |
| v3-500 / v3-100k | 500 / 100 000 | 499,32 / 99 863,63 | −0,14 % |

## Lecturas de los datos

1. **v2 está «en caja», como anticipó 03-plan-v3.md**: con RSI en `mean_reversion` (media ≈50) y
   `ma_trend` (≈47), sin el suelo del ATR (≈78) el compuesto ronda ≈49 y nunca alcanza el umbral
   absoluto de 60. v2 no produce información nueva (equivale a cash); se mantiene activa solo como
   referencia visual en `/compare`. v3 (rank-normalización) es su sucesora conceptual.
2. **v1 confirma el diagnóstico de 01/02**: churn de stop→recompra y compra de fuerza. Parte del
   churn era un **bug**, no estrategia — ver abajo.
3. **v3 es el brazo prometedor** pero lleva pocas sesiones; sin veredicto (≥20 sesiones).

## Bug HIGH encontrado en la revisión: HWM rancio en recompras

`portfolio_positions.high_water_mark` no se limpiaba al cerrar una posición (qty=0) ni al
recomprarla. La siguiente entrada heredaba el pico del viaje anterior — que por construcción está
por encima del precio que disparó el stop — así que el stop podía saltar **en el primer tick tras
la recompra** (bucle compra→venta cada cooldown). Confirmado en datos: todas las filas planas de
las carteras 1/2 conservaban picos viejos (p. ej. AMD hwm 545 con coste 477).

**Arreglos aplicados** (benefician a TODAS las versiones, son del adapter/level inferior):
- `PaperBroker._apply_sell`: al quedar plano, `high_water_mark = None` (además del unrealized P&L).
- `PaperBroker._apply_buy`: recompra sobre fila plana = posición nueva (coste = fill, HWM = None).
- `PaperBroker.place_order`: rechaza compras sin cash suficiente (slippage+comisión incluidos) —
  el doble de papel debe comportarse como el broker real del seam.
- `RiskManager.size_positions`: la reserva `MIN_CASH_PCT` se respeta SIEMPRE
  (`spendable = cash − total×reserva`), no solo el primer día (antes `min(cash, investable)`
  degeneraba a `cash` y gastaba la reserva a cero).
- `execute_paper_trades`: se salta con `STALE_ANALYSIS` si el último análisis no es de hoy;
  el guard de idempotencia ya no cuenta los protective-sell (un stop matinal no bloquea el run manual).
- `protective_sell`: savepoint por cartera (un fallo no revierte los stops de las demás).
- `composite_scorer`: cobertura CERO ⇒ HOLD (no liquidar por apagón de datos).
- Gates de calendario con fecha UTC (no local del contenedor).
- Limpieza one-shot de datos: `UPDATE portfolio_positions SET high_water_mark = NULL WHERE qty <= 0`.

## v4 = v3 + momentum (una sola variable nueva)

P11 se planificó en dos mitades; v4 activa la **fase 1** (momentum cross-seccional, synthesis §3.1).
La fase 2 (multiplicador de régimen macro, §3.2) queda para v5 — una variable por experimento.

- Nuevo indicador `PriceMomentum` (`signal_id="momentum"`): retorno sobre `period=126` barras
  terminando `skip=21` barras atrás (estilo 12-1 con lookback de 6 meses — la historia cargada,
  400 días naturales ≈ 275 barras, no da para 252+21), squash logístico (`sensitivity=5`).
- Los **parámetros viven en la base** (`config/strategy.yaml`) ⇒ todas las versiones lo computan y
  `run_analysis` lo **persiste en modo observación**; solo v4 le da **peso** (0.40 → renormalizado
  rsi .417 / ma .25 / momentum .333).
- Con `rank_normalize` (heredado de v3) el sub-score se convierte en el **percentil de momentum
  dentro del universo del día** = momentum relativo, exactamente la señal núcleo de synthesis §3.1.

### Medición (igual que v3)
- Brazos: v3 (control) vs v4 (delta = momentum). `/compare`, ≥20 sesiones, criterio pre-registrado:
  v4 mejora alfa acumulada vs v3 sin empeorar max-drawdown > 2 pp.
- Las significancias de `comparator.py` están implementadas (bootstrap + Jobson-Korkie/Memmel);
  queda pendiente el plumbing `load_summary`/`daily_returns`/`compare` para el veredicto formal.

## Deuda pendiente (de la revisión de código, no aplicada aún)
- **Retornos ajustados por flujos**: `daily_returns`/`period_pnl` tratan un depósito/retirada
  mid-periodo como P&L (hoy impacto 0 — solo existen los depósitos iniciales). Time-weighted returns
  usando `cash_movements`.
- **Round-trips sin comisión**: `build_round_trips` no resta comisiones (hoy `COMMISSION_*` = 0).
- mypy: 4 errores preexistentes en tests (CI solo gatea ruff).

## Handoff notes
- **Qué produje:** arreglos de broker/jobs/scorer (arriba), indicador momentum + config, overlay
  `config/strategies/v4.yaml`, tests (unit + integración), entrada v4 en `/info` (ES/EN).
- **Para el siguiente agente:** crear carteras `v4-500`/`v4-100k` vía API tras desplegar; v5 =
  multiplicador macro (P11 fase 2); implementar el plumbing del comparator para veredictos con p-valor.
