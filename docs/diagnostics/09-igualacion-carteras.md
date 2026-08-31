<!-- Agent: Experiment Tracker | Phase: 6 | Depends on: 08-revision-2026-08.md, docs/finance/experiment-framework.md -->

# Igualación de carteras y reglas del experimento (2026-08-31)

Decidido tras la revisión de agosto (`08-revision-2026-08.md`). Este documento fija **cómo se
compara** y **cuándo se mata** una versión, por escrito y por adelantado, para que la decisión no
dependa de cómo se vea la curva el día que se mire.

## 1. El problema que resuelve

Las carteras nacieron en fechas distintas: v1/v3/v5/v6 el 15-jun, v7/v8 el 22-jul, v10 el 31-jul.
Sus cifras «desde el inicio» responden a preguntas distintas — cada una lleva el régimen de
mercado que le tocó vivir — así que **ordenarlas entre sí no significa nada**. Peor: la que
arrancó en el peor momento parece la peor estrategia.

Dos cambios lo arreglan, uno de medida y otro de datos:

- **Medida:** `GET /api/algorithms/leaderboard` intersecta las fechas de NAV de todas las carteras
  y calcula retorno, índice, exceso, Sharpe y drawdown **sobre las mismas sesiones**. Las que no
  tienen datos en la ventana salen listadas en `excluded`, nunca omitidas en silencio. Visible en
  `/compare` como «Clasificación en ventana común».
- **Datos:** todas las carteras vivas se reinician a la vez, con el mismo capital y en efectivo
  al 100% (`scripts/reset_portfolios.sql`). A partir del reinicio la ventana común es toda la
  historia y la comparación es directa.

## 2. Cohorte tras la igualación

| Cartera | Versión | Capital | Motivo |
|---|---|---|---|
| v1-500 / v1-100K | v1 | 500 € / 100 000 € | Control absoluto (pierna «trend» del ensemble) |
| v3-500 / v3-100k | v3 | 500 € / 100 000 € | Única con alfa acumulada positiva (pierna «chop») |
| v7-500 / v7-100k | v7 | 500 € / 100 000 € | v3 con stops anchos: aísla el efecto del stop |
| v8-500 / v8-100k | v8 | 500 € / 100 000 € | Ensemble por régimen (v1↔v3) |
| v10-500 / v10-100k | v10 | 500 € / 100 000 € | Ensemble + confirmación de momento; la candidata |
| m3-500 / m3-100k | m3 | 500 € / 100 000 € | Único brazo micro (baja frecuencia) |

**Retiradas** (`active=false`, historial intacto): **v2** (nunca opera: composite ≈49 contra una
puerta absoluta de 60), **v5** y **v6** (−6,0 y −6,7 pp de exceso acumulado; su hipótesis —
multiplicador de régimen y pesos fundamentales — quedó absorbida por v10). Se conservan **m1**,
**m2** y **v4**, ya retiradas antes.

Los dos tamaños de capital se mantienen a propósito: 500 € comprueba que la estrategia sigue
siendo viable con posiciones fraccionadas y comisiones mínimas, 100 000 € da la señal limpia sin
ruido de redondeo.

## 3. Reglas de decisión (escritas antes de mirar los resultados)

### 3.1 Ventana mínima

Ninguna versión se promociona ni se retira con **menos de 20 sesiones comunes**: es el umbral que
ya usa el comparador (`_MIN_PAIRED_DAYS`) para emitir algo distinto de `INSUFFICIENT_EVIDENCE`.
Con el pipeline sano son unas 4 semanas de calendario.

### 3.2 Retirada de una versión diaria

Se retira (`active=false`) cuando, sobre la ventana común y con ≥20 sesiones, se cumple **una**:

- Exceso sobre el índice **< −5 pp**, o
- Exceso negativo **y** veredicto `B_BETTER` frente a v10 en `GET /api/algorithms/compare`
  (es decir, peor de forma estadísticamente significativa, no solo de aspecto), o
- **No opera** en toda la ventana (el caso v2: una versión que no toma decisiones no es una
  estrategia, es efectivo con pasos extra).

### 3.3 Criterio de muerte del microtrading

m1 murió por fricción: 2 430 fills, 14 032 € de comisiones y slippage sobre una pérdida total de
15 153 € — el 93%. m3 existe para probar una única hipótesis: **que a baja frecuencia quede edge
bruto por encima del coste**. Por tanto:

> **Fecha de juicio: 2026-09-30.** Si en ese momento m3 no ha acumulado, sobre la ventana común,
> un **edge bruto positivo** — retorno antes de costes (`realized_flow + commission_total +
> slippage_est`, vía `GET /api/portfolios/{id}/costs`) mayor que cero — **se apaga la sección
> micro entera** (`MICRO_ENABLED=false`) y no se lanza ninguna variante nueva.

El umbral es deliberadamente flojo (edge bruto > 0, no rentabilidad neta): si ni siquiera la
señal bruta gana dinero antes de pagar el spread, no hay nada que optimizar y cualquier
frecuencia mayor solo acelera la pérdida. Y es un umbral **con fecha**: m1 sobrevivió dos meses
justamente porque nadie había escrito cuándo pararlo.

### 3.4 Qué NO cuenta como evidencia

- Una ventana con jobs caídos: si la alerta de salud disparó durante el periodo, se anota y la
  ventana se descarta o se recorta.
- El acumulado desde la creación de cada cartera (§1).
- Un backtest solo. Los backtests calibran; **la decisión de retirar o promocionar se toma sobre
  resultados vivos**, que es la lección de v1 (ganaba el backtest largo y perdió un 11,6% en vivo).

## 4. Qué se conserva del historial anterior

El reinicio borra `trade_orders`, `portfolio_positions` y `portfolio_nav` de las carteras activas.
Antes se archiva todo en `~/.local/state/autonomous-trader/archive/`, fuera del repositorio.

> **Incidente del propio archivado (2026-08-31).** El primer volcado se hizo con
> `pg_dump --data-only -t portfolio_nav`, que sobre un **hypertable de TimescaleDB vuelca solo la
> tabla padre — siempre vacía**: las filas viven en los *chunks* de `_timescaledb_internal`. El
> archivo salió con 0 filas de NAV y la comprobación («las cinco tablas están») miró las cabeceras
> `COPY`, no las filas. El reinicio borró después las curvas reales.
>
> **Recuperado:** el ledger sí se archivó entero (7 152 órdenes), así que
> `scripts/rebuild_nav_from_ledger.py` reconstruye las curvas diarias desde las operaciones y las
> barras almacenadas → `pre-reset-nav-rebuilt.csv`. Contrastado contra las cifras del documento 08:
> v3, v8, v10, m1 y m3 coinciden al euro; v1 y v7 quedan un 0,02% y un 0,11% por debajo porque su
> última operación es anterior al 28-ago y la reconstrucción marca al cierre de cada sesión, no al
> del día anterior como hacía el job vivo. **Es una aproximación**: dilo allí donde se usen estas
> cifras.
>
> **Corregido para siempre:** `scripts/archive_portfolios.sh` usa `\COPY (SELECT * FROM …)`, que
> atraviesa el hypertable como cualquier consulta, y **falla si alguna tabla sale con 0 filas** —
> un backup que no se puede verificar no es un backup. Úsalo antes de cualquier operación
> destructiva; `pg_dump -t` sobre hypertables, nunca.

Los diagnósticos 01-08 contienen las conclusiones; el archivo está por si hiciera falta rehacer
una cifra concreta.

## Handoff notes

**Producido:**
- `PortfolioComparator.leaderboard()` + `GET /api/algorithms/leaderboard` + tabla en `/compare`.
- Este documento: cohorte, reglas de retirada y fecha de juicio del micro.
- Igualación ejecutada: v2/v5/v6 retiradas; v1, v3, v7, v8, v10 y m3 reiniciadas a la vez.

**Lo que el siguiente agente debe saber:**
- La ventana común arranca en el reinicio. Antes de esa fecha el leaderboard mezcla arranques
  distintos, así que si necesitas mirar atrás, usa `?start=` y sé explícito.
- Las reglas de §3 son el contrato del experimento. Cambiarlas a mitad de ventana invalida la
  ventana: si hay que cambiarlas, se cambian **y se reinicia el reloj**.
- El 2026-09-30 hay que juzgar m3 (§3.3). Está anotado también en `MEMORY.md`.
