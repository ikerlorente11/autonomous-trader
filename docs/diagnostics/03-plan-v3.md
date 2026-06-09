<!-- Agent: Investment Researcher | Phase: diagnóstico | Depends on: 01-diagnostico-perdidas, 02-plan-mejora -->

# Plan v3 — siguiente iteración de estrategia

> **Estado (DESPLEGADO, 2026-06-09):** **P7 + P10 + P12 implementados** y en `main`. v3 = v2 + P7.
> - **P7 — hecho (v3).** `scoring.rank_normalize` (campo nuevo en `ScoringConfig`, default `False`);
>   rank-norm cross-seccional en `engine.score_universe` (capa sobre el scorer), usada por
>   `run_analysis` y `execute_paper_trades`. Activo solo en `config/strategies/v3.yaml`.
> - **P10 — hecho (global).** Comisiones en `PaperBroker` (`COMMISSION_PCT` / `COMMISSION_PER_ORDER`,
>   env, default 0); columna nullable `trade_orders.commission` (migración `0009`); `compute_cash`
>   las resta (afecta caja/NAV, **no** capital aportado). Global a todas las versiones.
> - **P12 — hecho (global).** Gate de frescura `MAX_BAR_STALENESS_DAYS` (env, sesiones, default 0=off)
>   en `run_analysis` / `_ranked_for_engine` vía `calendar.nth_prior_trading_day`.
> - **Carteras vivas:** `v3-500` (id 6) / `v3-100k` (id 7), `strategy_label="v3"`.
> - **Pendiente:** **P11** (momentum cross-seccional + multiplicador macro) → **v4**, fase aparte; y
>   los stubs de significancia de `comparator.py` para juzgar el A/B con rigor (≥20 sesiones).
> - **Para activar comisiones/frescura:** poner `COMMISSION_PCT` / `MAX_BAR_STALENESS_DAYS` en `.env`
>   (defaults 0 dejan el comportamiento idéntico al actual).

> **Depende de:** `01-diagnostico-perdidas.md` (causas), `02-plan-mejora.md` (P1–P12).
> **Restricciones (CLAUDE.md):** paper-only, seam `BrokerAdapter` intacto, **nada hardcodeado**
> (todo en `config/strategy.yaml` / `config/strategies/<label>.yaml` / env), presupuesto RAM de la Pi.

## Dónde estamos (contexto para retomar)

- El sistema soporta **versión de estrategia por cartera** (`portfolios.strategy_label`, migración `0008`).
  Una versión es un overlay `config/strategies/<label>.yaml` deep-merged sobre `config/strategy.yaml`.
  El motor (`execute_paper_trades`) puntúa cada versión una vez y opera cada cartera con su config;
  `protective_sell` resuelve los stops por versión. Detalle en `CLAUDE.md` y `02-plan-mejora.md`.
- **Versiones existentes:** `v1` = base (control, comportamiento previo al diagnóstico) · `v2` =
  fixes P1–P6 (ATR fuera del score, RSI mean-reversion, ma_trend cap, cooldown de recompra, piso de
  stop, no piramidar). Fixes globales P8 (unrealized fantasma) y P9 (sellado del NAV / benchmark) ya aplicados.
- **Carteras vivas:** `V1-500`/`V1-100K` (v1, con ~10 días de histórico), `v2-500`/`v2-100k` (v2, desde hoy).
- **Comparación:** página `/compare` superpone las curvas NAV (% rebase o € absoluto) con crosshair compartido.
- **Observación del primer día de v2:** con el mercado sobrecomprado, v2 hizo **0 compras** (correcto: la
  lógica mean-reversion espera retrocesos). Es algo a vigilar — ver "Ajuste candidato de v2" abajo.

## Qué entra en v3 (recomendación)

v3 ataca lo que el plan dejó fuera de v2 por ser de mayor esfuerzo o estructural. **Mínimo recomendado: P7 + P10.**
P11 es una fase aparte por su tamaño.

| # | Cambio | De dónde | Esfuerzo | Por qué en v3 |
|---|---|---|---|---|
| **P7** | Rank-normalización **cross-seccional** de sub-scores antes de ponderar (synthesis §3.4) | 02-plan §P7 | Medio | El gate 60/45 hoy es absoluto y sesgado; normalizar a percentil del universo lo hace relativo y robusto. Es lo que más “profesionaliza” el scorer. |
| **P10** | **Modelo de comisiones** en `PaperBroker` (`COMMISSION_PCT`/`COMMISSION_PER_ORDER`) | 02-plan §P10 | Bajo | Hace visible el coste del churn en el A/B; hoy es 0 € y favorece artificialmente a las versiones que rotan mucho. |
| **P12** | Gating de **frescura de datos** antes de decidir/ejecutar | 02-plan §P12 | Bajo | Evita operar con barras stale; impacto € bajo hoy, importante de cara a broker real. |
| **P11** | Activar **momentum cross-seccional real + multiplicador macro** (señales núcleo del diseño, hoy *observation-only*) | 02-plan §P11, synthesis §3.1/§3.2 | **Alto** | El mayor salto estructural; mejor como **v4** o fase dedicada, no mezclar con P7/P10. |

### Ajuste candidato de v2 (decisión abierta, no es v3 per se)
Si v2 se queda demasiado tiempo en caja (0 compras repetidas), considerar en v2 **RSI `banded`** (alto cerca
de sobreventa, plano en el medio) en vez de `mean_reversion` puro — el campo `RsiParams.mode` ya contempla
`banded` en el modelo, **pero la rama `banded` NO está implementada** en `momentum.py` (hoy haría passthrough).
Implementarla es trabajo pequeño y podría ser parte de v3 o un ajuste de v2 tras ver datos.

## Cómo se implementa cada cosa (pasos concretos, NO aplicar aún)

### Arranque de v3 (mecánica de versión)
1. Crear `config/strategies/v3.yaml` (overlay). Empezar copiando los cambios de `v2.yaml` y **añadir** los de v3
   (P7/P10), para que v3 = v2 + extras y el A/B aísle el delta sobre v2.
2. `GET /api/strategies` la listará automáticamente (lee `config/strategies/*.yaml`).
3. Crear carteras `v3-500` / `v3-100k` (`POST /api/portfolios` + `PATCH …{strategy_label:"v3"}`), o reutilizar.
4. Recordatorio `extra="forbid"` en `backend/analysis/config.py`: **toda clave YAML nueva exige su campo pydantic**.

### P7 — rank-normalización cross-seccional
- El `composite_scorer` opera símbolo a símbolo (sin ver el universo), así que la normalización debe ir **una capa
  antes**, en `backend/analysis/engine.py`, sobre el conjunto de `IndicatorResult` del día (percentil/z-score por
  `signal_id` entre todos los símbolos), antes de pasar al scorer.
- Nuevo flag versionado: `scoring.rank_normalize: bool` → añadir campo a `ScoringConfig` (config.py) y activarlo en
  `v3.yaml`. Cuando está off (v1/v2/base) el pipeline no cambia.
- `run_analysis` y el `_ranked_for_engine` de `execute_paper_trades` deben aplicar la misma normalización (factorizar
  un helper para no divergir).
- Cuidado RAM (Pi): normalizar en memoria sobre el universo del día (~watchlist), sin materializar histórico.

### P10 — comisiones en PaperBroker
- En `backend/trading/paper_broker.py::place_order`, descontar comisión del cash y reflejarla en el ledger
  (un `trade_orders` extra o un campo). Parámetros por **env** (`COMMISSION_PCT`, `COMMISSION_PER_ORDER`), default 0
  (comportamiento actual). Sigue siendo detalle del **adapter** → seam intacto.
- Si se quiere por versión, llevarlo a `StrategyConfig.trading` (como cooldown/stop floor) en vez de env.

### P12 — gating de frescura
- Antes de puntuar/operar, comprobar que la última barra por símbolo no sea más vieja que N días hábiles
  (`MAX_BAR_STALENESS_DAYS`, env); si lo es, excluir el símbolo o degradar el run. `backend/data_ingestion/ingest.py`
  ya calcula validaciones que hoy son advisory (`report.ok` no se consume) — engancharlo ahí.

### P11 — momentum cross-seccional + macro (fase aparte / v4)
- Implementar las señales núcleo de `docs/research/00-signal-synthesis.md` §3.1 (momentum relativo del universo) y
  §3.2 (multiplicador de régimen macro, hoy `macro_regime` se registra pero no entra al scorer). Es estructural:
  toca el engine, el scorer y posiblemente el esquema de señales. Planificar por separado.

## Cómo se mide v3 (experimento)

- A/B/(C) por cartera: comparar `v1` (control) vs `v2` vs `v3` con la página `/compare` (alfa rebasada) y las
  métricas de `docs/finance/performance-metrics.md`.
- **Bloqueante de medición rigurosa:** los stubs de significancia en `backend/experiments/comparator.py`
  (`_significance_returns` bootstrap, `_significance_sharpe` Jobson-Korkie) **siguen sin implementar** — hacen falta
  para declarar un ganador con p-valor. Implementarlos es prerequisito de cualquier veredicto formal.
- **Aislar una variable por experimento:** v3 = v2 + (P7) y/o + (P10), no mezclar P7 y P11 en la misma corrida.
- **Horizonte:** ≥ 20 sesiones por brazo; con pocos días no hay potencia estadística.
- **Criterio de éxito (pre-registrar):** v3 mejora la alfa acumulada vs v2 con `p<0,05` sin empeorar el max-drawdown
  > 2 pp; P10 no debe “mejorar” por arte de magia (verifica que penaliza el churn como se espera).
- **Thesis-breaker:** si v3 no supera a v2 en ≥20 sesiones, revertir y reabrir hipótesis (anti-anchoring).

## Checklist para retomar en frío

- [ ] Decidir alcance de v3: ¿P7 + P10 (recomendado)? ¿incluir P12? ¿`banded` para v2?
- [ ] Implementar el/los cambios con su campo pydantic (recordar `extra="forbid"`).
- [ ] Crear `config/strategies/v3.yaml` (= v2 + delta v3).
- [ ] Tests (unit + integración) como en P1–P6; `./scripts/test.sh` en verde.
- [ ] Crear carteras `v3-*`, asignarles `strategy_label="v3"`, lanzar pipeline (“Run now”) para arrancar hoy.
- [ ] (Opcional) implementar los stubs de `comparator.py` para medir con rigor.
- [ ] Merge a `main` (PR), aplicar migración si la hubiera, verificar en vivo.

## Handoff notes

- **Qué produje:** este plan de v3 (P7 + P10 mínimo, P12 opcional, P11 como fase aparte), con pasos concretos, la
  mecánica de versión por cartera para arrancarla, y el diseño de medición.
- **Lo importante para el siguiente agente:** v3 debe partir de **v2** (v3 = v2 + delta) para que el A/B aísle el
  efecto; respetar `extra="forbid"`; los stubs de significancia de `comparator.py` siguen pendientes; y vigilar si v2
  se queda en caja (posible `banded`).
- **Nada aplicado.** Decisiones de calibración (umbrales de P7, comisiones) son del Experiment Tracker, no de aquí.
