<!-- Agent: Reality Checker | Phase: 6 | Depends on: 08-revision-2026-08.md, 09-igualacion-carteras.md -->

# Revisión de noviembre 2026 y fecha de cierre del proyecto

Corte de datos: **2026-11-18** (NAV del día incluido). Ventana común desde el reinicio del
2026-09-01: **56 sesiones**. Revisión hecha contra la DB de producción (pidev), `job_runs`, el
log de `health_alert.py` y los cgroups de los contenedores.

## Resumen ejecutivo

1. **La operativa está sana**: 0 sesiones con huecos de barras, 0 OOM, la DB en 32 MB de memoria
   anónima (437 MB en agosto) y un único job fallido en 11 semanas (FRED 502, 22-sep).
2. **Ningún brazo tiene alfa significativa** (p entre 0,25 y 0,92). Los que «baten» al índice lo
   hacen sobre un SPY que cae un 3,85 %, en buena parte por estar menos expuestos.
3. **v10 se retira** por la regla §3.2 del documento 09: exceso −6,5 pp sobre la ventana común.
4. **m3 aprobó su juicio del 30-sep**, pero el juicio no se había documentado y **la fórmula
   preinscrita estaba mal** (contaba la comisión dos veces). Con la fórmula corregida también
   aprueba a esa fecha; desde entonces su edge bruto ha caído a ≈ 0.
5. **El experimento no puede dar un veredicto en un plazo útil**: con la dispersión medida, separar
   un alfa de ±5 pp del ruido exigiría entre 17 y 64 años de sesiones (§4).
6. **Decisión del owner (2026-11-18): el proyecto tiene fecha de cierre el 2027-03-01**, con el
   criterio escrito en §5 antes de ver el resultado.

---

## 1. Salud operativa (2026-09-01 → 2026-11-18)

| Comprobación | Resultado |
|---|---|
| `GET /api/system/health` | OK (NAV al día, barras a 1 sesión, scheduler vivo) |
| Sesiones con cobertura incompleta de barras | **0** |
| Jobs `failed` | **1**: `fetch_macro_data` 2026-09-22, `FRED … BAMLH0A0HYM2: HTTP 502` |
| Episodios de alerta | 1: 2026-09-22 08:30 → 2026-09-23 08:00 (el mismo fallo; recuperado solo) |
| `trader-db` memoria anónima | **32 MB** (límite 640 MB), `oom_kill 0` |
| `trader-scheduler` / `trader-api` | 108 MB / 90 MB, `oom_kill 0` |
| Reinicios de contenedor | 0 (DB arriba desde 2026-09-08; api/scheduler desde el despliegue del 2026-11-09) |

- El `pool_recycle` de agosto resolvió la presión de memoria: `anon` lleva dos meses muy por
  debajo de 300 MB, que era la condición del documento 08 §1.1 para poder bajar el `mem_limit`.
  No se toca: con la fecha de cierre a la vista no compensa.
- El fallo del 22-sep solo afectó a series macro, que no alimentan a ningún brazo vivo como
  puerta. La ventana se anota (§3.4 del documento 09) pero no se recorta.
- `fetch_fundamentals` sale `degraded` en las 56 sesiones: los 6 ETF del watchlist (EFA, IWM, QQQ,
  SPY, TLT, VTI) no tienen fundamentales. Es cosmético.

## 2. Rendimiento sobre la ventana común

`GET /api/algorithms/leaderboard` (2026-09-01 → 2026-11-18, 56 sesiones, 0 excluidas):

| Cartera | Rentab. | Exceso vs SPY | Sharpe | Máx. DD | Alfa anual (IC 95 %) | p |
|---|---|---|---|---|---|---|
| v1-500 | −0,64 % | **+3,21 pp** | −0,25 | −7,52 % | +15,9 % (−67,6 / +102,8) | 0,73 |
| v1-100K | −0,75 % | +3,10 pp | −0,28 | −7,52 % | +15,4 % (−67,9 / +102,7) | 0,75 |
| m3-500 | −1,99 % | +1,86 pp | −10,05 | −2,11 % | +7,5 % (−54,9 / +71,4) | 0,85 |
| m3-100k | −2,00 % | +1,85 pp | −10,08 | −2,11 % | +7,5 % (−54,9 / +71,4) | 0,86 |
| v7-100k | −2,21 % | +1,64 pp | −1,63 | −3,02 % | +6,9 % (−37,0 / +51,3) | 0,79 |
| v8-500 | −2,78 % | +1,07 pp | −1,65 | −4,98 % | +4,3 % (−50,7 / +63,1) | 0,92 |
| v8-100k | −2,83 % | +1,02 pp | −1,67 | −4,99 % | +4,1 % (−49,4 / +60,5) | 0,92 |
| v7-500 | −2,99 % | +0,86 pp | −1,99 | −3,50 % | +3,2 % (−40,9 / +47,7) | 0,92 |
| *SPY buy & hold* | *−3,85 %* | — | *−1,33* | *−5,99 %* | — | — |
| v3-100k | −4,49 % | −0,64 pp | −2,89 | −4,72 % | −3,9 % (−47,7 / +40,0) | 0,82 |
| v3-500 | −4,63 % | −0,78 pp | −2,95 | −4,86 % | −4,6 % (−48,2 / +39,1) | 0,80 |
| **v10-500** | **−10,32 %** | **−6,47 pp** | −4,27 | −10,95 % | −32,3 % (−88,5 / +23,3) | 0,26 |
| **v10-100k** | **−10,39 %** | **−6,54 pp** | −4,27 | −11,04 % | −32,7 % (−88,4 / +22,3) | 0,25 |

Actividad (fills desde el reinicio): v1 86, v3 ~89, v7 63, v8 ~95, **v10 183**, m3 266 (todo
cerrado intradía). Trailing stops: entre 14 (v7) y 32 (v8) por cartera.

**Lecturas:**

- Ningún intervalo de confianza excluye el cero. Todo lo que hay en la columna «exceso» es
  compatible con ruido.
- Bajar menos que un índice que cae no es alfa: los brazos con más liquidez media (stops +
  puerta de score) tienen menos beta. m3 es el caso extremo: está en efectivo toda la noche.
- v10, la candidata que ganó el bake-off de julio, es la que más opera (el doble que el resto) y
  la peor de la ventana. Repite el patrón de las anteriores ganadoras: v1 en el backtest largo y
  v8 en julio también volvieron a la media en la ventana siguiente.

## 3. Decisiones de esta revisión

### 3.1 v10 se retira

Cumple el primer criterio de §3.2 (documento 09): exceso < −5 pp con ≥ 20 sesiones comunes, en las
dos carteras. Ejecutado el 2026-11-18 con `PATCH /api/portfolios/{24,25} {"active": false}`. Es una
de las excepciones tasadas de la moratoria (retirada según las reglas escritas).

- Las carteras tenían 8 posiciones abiertas cada una (36 682 € de coste en la de 100k, 183 € en la
  de 500). **No se liquidan**: los jobs filtran por `active_only`, así que el registro queda
  congelado en el NAV del 2026-11-18, que es el que entra en cualquier comparación posterior.
- El segundo criterio de §3.2 («exceso negativo **y** `B_BETTER` frente a v10») se queda sin
  referencia. **No se reescribe**: cambiar reglas a mitad de ventana reinicia el reloj, y desde
  ahora el veredicto se lee del leaderboard frente a SPY (§5).

### 3.2 Juicio de m3 (pendiente del 2026-09-30) y corrección de la fórmula

La fórmula del documento 09 §3.3 era `realized_flow + commission_total + slippage_est`. Pero en el
código (`backend/db/queries/portfolio_queries.py`, `portfolio_costs`) `realized_flow` es
`sell_notional − buy_notional`: la comisión se cobra aparte y **no** está restada ahí, mientras
que el slippage sí va incluido en el precio de cada fill. Sumar la comisión la cuenta dos veces.
**Edge bruto correcto = `realized_flow + slippage_est`.** Comprobación: `realized_flow −
commission_total` reproduce la rentabilidad neta del leaderboard (m3-500: −6,88 − 3,31 = −10,19 € ≈
−2,0 %).

Recalculado desde `trade_orders` (todo cerrado intradía, sin posiciones abiertas en ningún corte;
`SLIPPAGE_PCT = 0,001`):

| Cartera | Corte | Fills | realized_flow | slippage_est | **Edge bruto (corregido)** | Fórmula del doc 09 |
|---|---|---|---|---|---|---|
| m3-500 | 2026-09-30 | 92 | +0,90 € | 2,30 € | **+3,20 €** | +4,35 € |
| m3-100k | 2026-09-30 | 92 | +176,71 € | 460,62 € | **+637,33 €** | +867,64 € |
| m3-500 | 2026-11-18 | 266 | −6,88 € | 6,61 € | **−0,27 €** | +3,04 € |
| m3-100k | 2026-11-18 | 266 | −1 378,77 € | 1 322,60 € | **−56,17 €** | +605,13 € |

- **Veredicto del 2026-09-30: m3 aprueba** con cualquiera de las dos fórmulas, así que dejarla
  viva fue correcto. Queda documentado aquí con dos meses de retraso.
- **Desde entonces el edge bruto es ≈ 0** (−0,05 % del capital). El juicio de §3.3 era de una sola
  vez y no se reabre; m3 sigue en el cohorte hasta el cierre (§5).

## 4. Por qué el experimento no puede dar un veredicto a tiempo

La anchura del IC del alfa con 56 sesiones va de ±44 pp (v7-100k) a ±85 pp (v1). El error estándar
baja con la raíz del número de sesiones, así que para estrecharlo a ±5 pp harían falta
`56 × (44/5)² ≈ 4 300` sesiones (**~17 años**) en el mejor caso y `56 × (85/5)² ≈ 16 000` (**~64
años**) con v1. Además hay 5 estrategias vivas: con p < 0,05 sin corregir, la probabilidad de que
al menos una salga «significativa» por puro azar ronda el 23 %.

Esto explica por qué cada ganadora regresó a la media en la ventana siguiente: el diseño no tiene
potencia para distinguir una estrategia buena de una con suerte en meses, y sobre datos diarios
gratuitos de 62 valores grandes de EE. UU. tampoco hay razón *a priori* para esperar un alfa grande.

## 5. Cierre del proyecto: 2027-03-01 (decisión del owner, 2026-11-18)

Escrito **antes** de conocer el resultado, con el mismo contrato que el documento 09: cambiarlo
después invalida la decisión.

### 5.1 Hasta el 2027-03-01

- El sistema sigue corriendo **tal cual**. La moratoria del documento 09 §3.5 sigue en vigor, con
  dos cambios:
  - **Se elimina la salida anticipada por «veredicto con significancia»**: un p < 0,05 a mitad de
    ventana ya no levanta la moratoria (§4: sería, con bastante probabilidad, un falso positivo).
  - **Se cancela el trabajo de tesis** (señales de eventos del documento 13 y momentum mensual del
    documento 10). Los datos ya ingeridos se quedan; no se calibra ni se diseña nada nuevo.
- Solo se permiten: retiradas por §3.2 (primer criterio) y arreglos de fiabilidad que no cambien
  el comportamiento de trading.

### 5.2 Juicio final del 2027-03-01

Sobre la ventana común (desde 2026-09-01), con `GET /api/algorithms/leaderboard`:

- **El proyecto continúa** solo si algún brazo vivo tiene **alfa anual positiva con
  p < 0,01 en sus dos carteras** (500 € y 100k). El 0,01 es 0,05 corregido por las 5 estrategias
  vivas (Bonferroni). En ese caso no se lanza nada nuevo: ese brazo se observa 6 meses más
  sin tocarlo (hasta 2027-09-01) como confirmación, con el mismo umbral, y si no lo mantiene se
  aplica §5.3.
- **En cualquier otro caso, el proyecto se archiva** (§5.3). No hay prórrogas ni «una última
  versión».

### 5.3 Qué significa archivar

1. `scripts/archive_portfolios.sh` (nunca `pg_dump -t` sobre hypertables) para guardar el ledger
   y las curvas en `~/.local/state/autonomous-trader/archive/`, comprobando filas.
2. Todas las carteras a `active=false`; `docker compose down` en pidev (el volumen de la DB se
   conserva hasta comprobar el archivo), quitar las entradas de cron de `deploy.sh` y
   `health_alert.py`.
3. Documento final `12-conclusiones.md`: qué se probó, qué se aprendió y por qué no hubo alfa.
4. El repositorio sigue público como pieza de portfolio. Marcarlo como *archived* en GitHub y
   actualizar su fila de Notion a «Archivado» se decide en ese momento.

## Handoff notes

**Producido:**
- Carteras 24 y 25 (v10) desactivadas el 2026-11-18; registro congelado en el NAV de ese día.
- Juicio de m3 del 2026-09-30 documentado (§3.2) y fórmula del edge bruto corregida.
- Fecha y criterio de cierre (§5), reflejados en `CLAUDE.md` y en el documento 09.
- `scripts/closure_reminder.py` + cron del host (`0 9 1 3 *`): el 2027-03-01 lee el leaderboard,
  aplica §5.2 y envía por correo el veredicto y los pasos de §5.3 (mismo SMTP que
  `health_alert.py`; `--dry-run` y `--test` para probarlo). Solo actúa ese día.

**Lo que el siguiente agente debe saber:**
- **Cohorte vivo desde el 2026-11-18:** v1, v3, v7, v8 (diarias) y m3 (micro), en sus carteras de
  500 € y 100k.
- **No lances, calibres ni ajustes nada.** El único trabajo legítimo hasta el 2027-03-01 es
  mantenerlo vivo y aplicar §3.2 si algún brazo cae por debajo de −5 pp.
- El 2027-03-01 se aplica §5.2 tal como está escrito. Si alguien propone cambiar el umbral ese
  día, la respuesta está en §4.
- Para el edge de cualquier cartera, `realized_flow + slippage_est`: **no** sumes la comisión.
