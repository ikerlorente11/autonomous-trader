<!-- Agent: Claude (autonomous session) | Phase: post-5 diagnostics | Depends on: 05-plan-v5-v6.md -->

# Filtro de mercado ("esperar al buen momento") + reseteo de carteras

Fecha: 2026-06-13. Petición del owner: resetear las carteras para comparar v1–v6 desde cero,
asegurando que **no invierten "por obligación al arrancar"** sino que **esperan a un buen
momento, incluso la primera vez**; y dejar docs + web al día.

## 1. ¿Había inversión forzada de arranque? — NO

Revisión del camino de ejecución (`PortfolioManager.execute_signals` → `RiskManager.size_positions`
→ `PaperBroker.place_order`): las entradas están **100% gobernadas por la acción del scorer**
(`BUY` solo si `score ≥ min_score_to_act`). No existe ninguna regla de "desplegar caja al
empezar" ni "mínimo de posiciones". Lo que el owner observó (v1 compró 8 nombres el 2026-05-29,
su primer día, justo antes de la corrección de junio) fue v1 haciendo su trabajo: compra fuerza,
y ese día 8 nombres cruzaron el umbral 60. No es un bug de arranque; es la tesis de v1 (y su
debilidad conocida, doc 01).

**Pero sí faltaba una pieza:** ninguna versión tenía un filtro de "¿es buen momento para comprar
EN GENERAL?". v1/v2 puntúan en absoluto; v3–v6 normalizan por percentil, así que **los mejores
del universo siempre cruzan el umbral cualquier día** → entrarían el día 1 pase lo que pase en el
mercado. El multiplicador de régimen (v5/v6) amortigua, pero no detiene la entrada.

## 2. Filtro de mercado (la pieza nueva)

`ranker.market_filter` (opcional; en la **config base**, así que TODAS las versiones lo heredan):
bloquea entradas nuevas (`BUY → HOLD`) los días en que el benchmark (SPY) cierra **por debajo de
su media móvil larga** (tendencia primaria bajista). Ventas y holds nunca se bloquean. Vive en
`engine.score_universe` (lo captura el backtester), es absoluto y universal, y gobierna el primer
run / una cartera recién reseteada igual que cualquier día. Fail-open: si falta el benchmark o
historia, no bloquea (nunca por falta de datos).

## 3. Calibración (backtest, ventana 2024-09 → 2026-06, SPY +33.6%)

**v1** (representativo agresivo) y **v4** (mejor de la familia disciplinada):

| | v1 return | v1 Sharpe | v1 maxDD | v4 return | v4 Sharpe | v4 maxDD |
|---|--:|--:|--:|--:|--:|--:|
| **sin filtro** | +52.2% | 1.01 | −21.2% | +19.0% | 0.58 | −10.3% |
| **filtro 100d** | +37.8% | 0.87 | −11.5% | +6.9% | −0.05 | −8.3% |
| **filtro 200d** | +38.0% | 0.87 | −13.6% | +6.9% | −0.05 | −9.4% |

Universo completo con 200d: v1 +38.0 / v3 −1.1% / v4 +6.9% / v6 +5.0% (todas bajan retorno y
Sharpe, todas mejoran o igualan drawdown).

**Lectura honesta:**
- El filtro **hace lo pedido**: se queda fuera en tendencia bajista y **reduce el drawdown de v1
  del −21% al −14%** (−11.5% con 100d).
- **Cuesta retorno** en todas las versiones. Es lo esperado: la ventana es fuertemente alcista
  (SPY +33.6%) y *cualquier* filtro de tendencia pierde upside en un mercado alcista sostenido.
- 100d y 200d dan retorno casi idéntico; 100d protege ~2pp más de drawdown. Esa diferencia está
  dentro del ruido — elegir 100d por ajustar 2pp mejor *esta* ventana sería sobreajuste. **Se
  elige 200d**: la línea bull/bear estándar, la más robusta fuera de muestra.

**Por qué se incluye pese a costar retorno en el backtest:** el valor de un filtro de tendencia
aparece en **bajistas sostenidos** (2022, 2008), que **no están en esta ventana** — juzgarlo solo
aquí lo infravalora, el espejo exacto del error de v2–v6 (sobreajustar una muestra bajista pequeña
en vivo). El owner priorizó explícitamente "no comprar en mal momento" sobre maximizar el retorno
de una ventana alcista. El forward-test dirá si protege cuando toque. Quien quiera v1 puro puede
poner `market_filter: null` en `v1.yaml`.

## 4. Reseteo de carteras

`scripts/reset_portfolios.sql`: borra trades/posiciones/NAV de las 12 carteras activas y re-fecha
el depósito de cada una a `now()` (capital nominal intacto: 500 € / 100 000 €). Quedan **planas,
100% en caja, con fecha de inicio común** → comparación v1–v6 desde cero. Tras el reset, la próxima
corrida re-entra **solo** si las señales de cada versión lo dicen **y** el filtro de mercado lo
permite — sin compra forzada de día 1.

## 5. Siguientes pasos
- ~20 sesiones forward (≈ mediados julio 2026): comparar v1–v6 ya con el filtro y desde el mismo
  arranque; ver si el filtro ayuda en una corrección real.
- Si aparece un bajista sostenido, es la primera ocasión de validar el filtro de verdad.
- v7 candidato (sin cambios respecto a 05): vol-targeting + límite de correlación.

## Handoff notes
- **Qué produje:** verificación de no-forced-entry; filtro de mercado (config base + engine +
  tests); calibración 100/200d; `scripts/reset_portfolios.sql`; reseteo de las 12 carteras; docs
  (este, CLAUDE.md) + web `/info` (sección "cuándo invierte", ES/EN).
- **Para el siguiente agente:** el filtro está en base → toca todas las versiones; el backtester
  lo respeta; calibrar cualquier ajuste ahí antes de tocar vivo.
