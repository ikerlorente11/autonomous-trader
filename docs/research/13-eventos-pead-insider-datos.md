<!-- Agent: TrendResearcher | Phase: post-5 | Depends on: 00-signal-synthesis, 02-news-sentiment-smartmoney -->

# Factibilidad de datos: PEAD (sorpresas de earnings) e Insider Form 4

**Pregunta que responde este documento:** ¿existen datos históricos GRATUITOS suficientes para
construir un histórico backtesteable **2023-04 → hoy** de estas dos señales, para los ~62 símbolos
del watchlist, dentro de los límites de una Raspberry Pi 4? Verificado contra endpoints reales
(agosto 2026), no de memoria. Las señales en sí ya fueron priorizadas en
`02-news-sentiment-smartmoney.md` (§1.2, §3.1) y `00-signal-synthesis.md` (Tier 2, #9-#12);
aquí solo se juzga el DATO.

---

## Resumen ejecutivo

| Señal | Veredicto | Fuente de backfill | Fuente incremental | Riesgo principal |
|---|---|---|---|---|
| **PEAD / sorpresa de earnings** | **GO (condicional)** | Alpha Vantage `EARNINGS` — verificado: histórico ~30 años con `estimatedEPS`, `reportedEPS`, `surprise`, `reportedDate` y **`reportTime`** (pre/post-market); 62 símbolos = ~3 días de backfill a 25 req/día | Finnhub `/stock/earnings` (últimos 4 trimestres en free — suficiente para refresco) | La **procedencia point-in-time del `estimatedEPS`** no está garantizada por contrato; exige validación cruzada antes de fiarse (ver §3) |
| **Insider Form 4** | **GO** | SEC **Insider Transactions Data Sets** — ZIPs trimestrales TSV, cobertura completa desde 2006Q1, gratis, sin key | EDGAR `data.sec.gov/submissions/CIK….json` (incluye `acceptanceDateTime`) + XML del Form 4; 10 req/s con User-Agent | Ninguno bloqueante. Usar **fecha de FILING** (no de transacción) como disponibilidad; cuidado con Form 4/A (enmiendas) |

La condición del GO de PEAD: **antes de backtestear, validar el vintage de las estimaciones**
(§3.1). Un backtest de PEAD con estimaciones revisadas a posteriori mediría una señal que no
existió — peor que no tener backtest.

**yfinance queda descartado como fuente de histórico de earnings** (contrariamente a lo que asumía
la síntesis §2.2): la comunidad y la propia API confirman que `earnings_history` solo devuelve los
**últimos 4 trimestres**, y `get_earnings_dates` (limit=12 por defecto) devuelve fechas pero con
estimaciones incompletas y horas poco fiables para el pasado. Sirve como calendario de PRÓXIMOS
earnings, no como histórico.

---

## 1. PEAD — detalle por fuente

### 1.1 Alpha Vantage `EARNINGS` — **la fuente de backfill** ✅

Verificado ejecutando el endpoint real (`query?function=EARNINGS&symbol=IBM&apikey=demo`):

- **Campos por trimestre:** `fiscalDateEnding`, `reportedDate`, `reportedEPS`, `estimatedEPS`,
  `surprise`, `surprisePercentage`, **`reportTime`** con valores `"pre-market"` / `"post-market"`.
- **Profundidad real:** IBM devuelve desde **1996** (fiscalDateEnding 1996-03-31, reportedDate
  1996-04-17) hasta 2026Q2 — ~30 años, sobradísimo para 2023-04 → hoy.
- **Límite free tier:** **25 requests/día** por cuenta (mismo cupo diario global ya verificado en
  el doc 02 para NEWS_SENTIMENT). Coste del backfill: 1 request por símbolo → **62 símbolos ≈ 3
  días de calendario** (y menos: los ETFs del watchlist no tienen earnings — solo las ~30-40
  acciones). Refresco trimestral posterior: irrelevante (o se delega en Finnhub, §1.2).
- **Punto fuerte diferencial:** es la única fuente gratuita verificada que da **fecha Y franja
  horaria del anuncio** junto con estimación y sorpresa en el mismo registro. `reportTime` resuelve
  la ambigüedad crítica del backtest: un anuncio *post-market* del día d solo es accionable en la
  apertura de d+1; uno *pre-market* del día d ya condiciona la sesión d.
- **Puntos débiles:** (a) algunos trimestres antiguos traen `estimatedEPS: None` — tratable, 
  el registro se descarta y la señal renormaliza (§3.3 de la síntesis); (b) procedencia del
  estimate no documentada → riesgo de lookahead, ver §3.1; (c) ToS free tier = uso personal
  no comercial (compatible con este proyecto).

### 1.2 Finnhub `/stock/earnings` — incremental sí, backfill NO

- Verificado: en free tier las EPS surprises están **limitadas a los últimos 4 trimestres**.
  Campos: `actual`, `estimate`, `surprise`, `surprisePercent`, `period`, `quarter`, `year`.
- **NO sirve para backfill** 2023→hoy. **SÍ sirve como job incremental**: un pull
  semanal/diario de 4 trimestres × 62 símbolos cabe de sobra en 60 calls/min, y como el proyecto
  ya tiene `FINNHUB_API_KEY` cableada, es el refresco natural una vez el backfill AV esté hecho.
- `/calendar/earnings` añade el campo `hour` (`bmo`/`amc`/`dmh`) — útil en vivo; su rango
  histórico en free tier **no está verificado** (no asumirlo para backfill).
- Uso adicional: los 4 trimestres que solapan con Alpha Vantage son el **conjunto de validación
  cruzada** del §3.1 — dos vendors independientes coincidiendo en estimate/actual da confianza.

### 1.3 yfinance — descartado como histórico ❌

- `earnings_history` / `get_earnings`: **solo últimos 4 trimestres** (confirmado en la discusión
  oficial del repo; los propios usuarios remiten a Finnhub/Alpha Vantage para historia).
- `get_earnings_dates(limit=12)`: devuelve fechas pasadas y futuras con `EPS Estimate` /
  `Reported EPS` / `Surprise(%)`, pero la profundidad con estimación poblada es corta, y los
  timestamps intradía que trae el índice no son una fuente fiable de BMO/AMC para el pasado.
- **Papel que le queda:** calendario de próximos earnings para la ventana de de-risk (Tier 1 #8
  de la síntesis) — eso ya funcionaba y no cambia.

### 1.4 Nasdaq API (`api.nasdaq.com/api/calendar/earnings?date=`) — secundaria, no oficial ⚠️

- Endpoint interno sin documentar; funciona para fechas pasadas arbitrarias (existen wrappers
  como `finance_calendars` que lo explotan por fecha), devuelve EPS forecast/actual y franja
  (`time-pre-market` / `time-after-hours` / `time-not-supplied`).
- **Fragilidad alta**: requiere headers de navegador, puede cambiar o capar sin aviso, y un
  backfill por FECHA (una request por día de calendario × 3 años ≈ 750+ requests) es la forma
  incorrecta de consumirlo para 62 símbolos. **No construir sobre él**; solo como contraste
  puntual de la franja horaria si AV y EDGAR discrepan.

### 1.5 SEC XBRL / Frames — actuals sí, sorpresa no; y el as del timing: el 8-K 2.02 ✅

- `data.sec.gov` (companyconcept/frames) da el **EPS reportado** con precisión regulatoria, pero
  **no existen estimaciones de consenso en la SEC** → la sorpresa no se puede computar solo con
  SEC. Además el dato XBRL llega con el 10-Q/10-K, semanas después del anuncio → inútil para
  timing de PEAD.
- **Pero:** el anuncio de resultados en sí es un **8-K item 2.02**, y el JSON de submissions de
  EDGAR incluye **`acceptanceDateTime`** (timestamp exacto de aceptación del filing). Es la fuente
  point-in-time **perfecta y gratuita** para verificar CUÁNDO vio el mercado cada anuncio — el
  árbitro cuando `reportedDate`/`reportTime` de un vendor genere dudas, y cobertura completa para
  todo el periodo 2023→hoy.

### 1.6 Composición recomendada para PEAD

```
Backfill 2023-04→hoy : Alpha Vantage EARNINGS   (estimate, actual, surprise, fecha, franja)
Validación vintage   : Finnhub 4Q solapados + 8-K 2.02 acceptanceDateTime (muestra aleatoria)
Incremental en vivo  : Finnhub /stock/earnings (+ /calendar/earnings para el hour del día)
Árbitro de timing    : EDGAR submissions acceptanceDateTime del 8-K 2.02
```

---

## 2. Insider Form 4 — detalle por fuente

### 2.1 SEC Insider Transactions Data Sets (bulk trimestral) — **backfill** ✅

- Verificado: la SEC publica **ZIPs trimestrales de TSV** en
  `sec.gov/files/structureddata/data/insider-transactions-data-sets/{YYYY}q{N}_form345.zip`,
  con cobertura desde **enero de 2006** (todo el mercado, todos los filers). Backfill 2023-04→hoy
  = ~14 ficheros.
- Hasta 8 tablas por trimestre (readme oficial de la SEC): SUBMISSION (accession, fecha de
  filing, CIK y **ticker del issuer**), REPORTINGOWNER (rol: officer/director/10%),
  NONDERIV_TRANS (fecha de transacción, **código de transacción** — el `P` que queremos —,
  acciones, precio, adquisición/disposición, acciones tras la operación), DERIV_TRANS, holdings
  y footnotes. Es exactamente el insumo del cluster-buying del doc 02 §3.1 sin parsear un solo XML.
- **Lag estructural:** el trimestre en curso solo se publica al cerrar el trimestre (los filings
  posteriores a las 17:30 ET del último día hábil caen en el siguiente ZIP). El bulk es para
  HISTORIA; el hueco desde el último ZIP hasta hoy lo cubre el incremental (§2.2).
- **Coste Pi:** ficheros de decenas de MB por trimestre con cientos de miles de filas de mercado
  completo — se procesa **en streaming/chunks filtrando por los ~40 CIKs de acciones del
  watchlist** y se descarta el resto; nunca cargar el TSV entero en memoria. Trabajo one-shot,
  puede correr de madrugada. Sin riesgo real para 4 GB si se hace con chunking.

### 2.2 EDGAR APIs — **incremental** ✅

- `data.sec.gov/submissions/CIK##########.json`: por cada CIK, arrays paralelos con
  `accessionNumber`, `form`, `filingDate`, **`acceptanceDateTime`**, `primaryDocument`. Filtrar
  `form == "4"` y bajar el XML (`sec.gov/Archives/edgar/data/{cik}/{accession}/…xml`).
- **Rate limit verificado:** ~10 req/s, y **User-Agent identificativo obligatorio** (sin él,
  403). Sin cupo diario. 62 CIKs/día + los XML nuevos (pocos por día en mega-caps) es una carga
  ridícula para el límite y para la Pi.
- **Parseo:** XML de schema fijo (`ownershipDocument`): `transactionCode`,
  `transactionDate`, `transactionShares`, `transactionPricePerShare`, `officerTitle`,
  `isDirector`… `xml.etree` de la stdlib basta; esfuerzo moderado y acotado (un parser, un schema).
  Mapeo ticker→CIK con `sec.gov/files/company_tickers.json` (oficial, gratis).
- La **EDGAR Full-Text Search** (`efts.sec.gov`, archivo 2001+, mismos límites) es una vía
  alternativa de descubrimiento, pero con submissions por CIK no hace falta.

### 2.3 OpenInsider (scrape) — prototipo, no cimiento ⚠️

- Screener HTML con parámetros de fecha/profundidad, parseable con `pandas.read_html`; hay
  scrapers públicos que reconstruyen historia amplia (el sitio cubre desde ~2003). Pre-agregado
  (cluster screens listos) — por eso el doc 02 lo proponía como prototipo.
- **Fragilidad:** sin API ni contrato, cualquier cambio de HTML rompe el parser, y scraping
  masivo para backfill es hostil e innecesario **cuando la SEC regala el mismo dato en TSV
  estructurado** (§2.1). Con los bulk datasets disponibles, OpenInsider pierde su razón de ser
  incluso como prototipo: mismo esfuerzo, peor contrato. **Recomendación: saltárselo.**

---

## 3. Riesgos de lookahead — leer antes de backtestear

1. **Vintage del `estimatedEPS` (Alpha Vantage) — el riesgo #1 del PEAD.** AV no documenta si el
   estimate por trimestre es el consenso congelado en la fecha del anuncio o un valor revisado.
   La práctica del sector (registros tipo Zacks) es congelarlo al anuncio, y que el campo
   `surprise` venga pre-computado sugiere eso — pero **sugerir no es garantizar**. Validación
   obligatoria antes del backtest: (a) contrastar los 4 trimestres solapados con Finnhub en los
   62 símbolos; (b) muestrear ~20 anuncios y comprobar sorpresa/fecha contra la prensa del día y
   el 8-K. Si el estimate resultara revisado → la señal SUE es inservible de esta fuente y el
   veredicto pasa a NO-GO (quedaría solo el drift post-gap sin sorpresa estandarizada, señal más
   pobre).
2. **Hora del anuncio.** Sin BMO/AMC, un backtest diario asigna mal la sesión de reacción
   (día-1 de un AMC es d+1, no d) y contamina el gate "sorpresa × signo de la reacción día-1"
   (doc 02 §1.2). `reportTime` de AV cubre el histórico; el `acceptanceDateTime` del 8-K 2.02 es
   el árbitro. **Regla dura:** anuncio AMC del día d → señal disponible en la apertura de d+1;
   BMO del día d → disponible en la apertura de d (nuestro fill ya es market-on-open de la sesión
   siguiente a la decisión, coherente con esto).
3. **Form 4: fecha de FILING, nunca de transacción.** La transacción puede ser hasta 2 días
   hábiles anterior al filing; el mercado solo ve el filing. El backtest debe indexar por
   `filing_date` (bulk) / `acceptanceDateTime` (incremental) y activar la señal en la apertura
   siguiente. Indexar por `transaction_date` es lookahead de 1-2 días — suficiente para inventarse
   todo el alpha de una señal de drift.
4. **Enmiendas (Form 4/A) y duplicados.** Un 4/A corrige un 4 previo; ingerir ambos duplica la
   compra. Clave natural `(accession_number, seq)` + regla: el 4/A sustituye al original pero
   **conserva la fecha de disponibilidad del original** (el mercado ya lo había visto).
5. **Survivorship del universo.** El watchlist son 62 símbolos vivos hoy; cualquier backfill
   sobre ellos hereda sesgo de supervivencia. Para **comparar versiones de estrategia entre sí**
   sobre el mismo universo (el uso real de este proyecto) es aceptable; para estimar alpha
   absoluto de PEAD/insider "en general", no. Nota: en mega-caps el drift PEAD documentado es el
   más débil (doc 02 §1.2, small-cap effect) — expectativas moderadas, y razón de más para
   backtestear antes de dar peso.
6. **Datos de la SEC ≈ completos por construcción** (obligación legal de filing); los de vendor
   (AV/Finnhub) pueden tener huecos por símbolo/trimestre. Persistir `data_completeness` como ya
   exige la síntesis §3.3, y descartar el trimestre sin estimate en vez de imputar.

---

## 4. Feasibilidad Raspberry Pi

| Concepto | Volumen | Veredicto |
|---|---|---|
| Backfill earnings (AV) | ~40 acciones × ~14 trimestres ≈ **560 filas**; 40 requests repartidas en ~2-3 días por el cupo de 25/día | Trivial |
| Backfill insider (SEC bulk) | ~14 ZIPs × decenas de MB, procesados en chunks filtrando ~40 CIKs → estimación **10²-10³ filas útiles** para mega-caps | OK con streaming; one-shot nocturno |
| Incremental diario | 1 call Finnhub/símbolo/semana + 62 submissions JSON/día + XMLs nuevos (pocos/día) | Muy por debajo de 60/min y 10/s |
| Almacenamiento | Dos tablas nuevas, filas evento-driven (~10³-10⁴ total) | Insignificante frente a `market_bars` |

Dentro de presupuesto en RAM, red y disco. El único cuello real es el cupo de 25/día de AV, que
solo afecta al backfill one-shot.

---

## 5. Ingesta propuesta (sin implementar)

Encaja en los seams existentes: providers tipados bajo `backend/data_ingestion/providers/`,
jobs idempotentes market-day-gated que degradan sin key, tablas Alembic, señal computada en
observación antes de recibir peso (el mismo camino que `revenue_accel`/`news_buzz`).

### Tablas

```sql
-- Sorpresas de earnings (una fila por símbolo y anuncio)
earnings_events (
  symbol            text,
  fiscal_period_end date,
  announce_date     date,          -- reportedDate del vendor
  announce_session  text,          -- 'bmo' | 'amc' | 'dmh' | 'unknown'  (reportTime/hour)
  available_ts      timestamptz,   -- primera apertura en la que la señal es accionable (regla §3.2)
  eps_estimate      numeric NULL,
  eps_actual        numeric,
  surprise_pct      numeric NULL,
  source            text,          -- 'alpha_vantage' | 'finnhub'
  PRIMARY KEY (symbol, fiscal_period_end)
)

-- Transacciones insider (una fila por transacción de un filing)
insider_transactions (
  accession_no      text,
  txn_seq           int,
  symbol            text,
  issuer_cik        text,
  filing_date       date,          -- lo que vio el mercado (clave point-in-time)
  acceptance_ts     timestamptz NULL,
  transaction_date  date,
  transaction_code  text,          -- 'P','S','M','A',...
  is_officer        bool, is_director bool, officer_title text NULL,
  shares            numeric, price numeric NULL, shares_after numeric NULL,
  is_amendment      bool,
  source            text,          -- 'sec_bulk' | 'edgar_api'
  PRIMARY KEY (accession_no, txn_seq)
)
```

Sin hypertable (volumen evento-driven minúsculo — coherente con la síntesis §6/Database
Optimizer). Las claves naturales dan la idempotencia de upsert que exige CLAUDE.md.

### Providers (Protocols nuevos, mismo patrón que `macro/`, `news/`)

- `providers/earnings/alpha_vantage_earnings.py` (backfill; degrada si falta
  `ALPHA_VANTAGE_API_KEY`) y `providers/earnings/finnhub_earnings.py` (incremental; reutiliza
  `FINNHUB_API_KEY`).
- `providers/insider/edgar_insider.py` (submissions JSON + Form 4 XML; `SEC_USER_AGENT`
  obligatorio en `.env`) y un lector one-shot de los bulk TSV para el backfill.

### Jobs

1. **Backfill (scripts one-shot, estilo `scripts/backfill_bars.py`, idempotentes):**
   `scripts/backfill_earnings.py` (AV, respeta el cupo 25/día — reanudable entre días) y
   `scripts/backfill_insider.py` (ZIPs bulk 2023Q2→último publicado, chunked por CIK).
2. **`fetch_earnings_surprises`** — extensión natural del job existente `fetch_fundamentals`
   (06:45 UTC), no un job nuevo: 4 trimestres Finnhub por símbolo con upsert; skip limpio sin key.
3. **`fetch_insider_filings`** — job diario nuevo en la franja 06:xx: submissions por CIK del
   watchlist, filtra Form 4 de los últimos ~3 días (latencia legal de 2 días hábiles, doc 02
   §3.1), parsea XML, upsert. Con timeout de wall-clock como el resto (regla de agosto 2026).
4. **Señales en OBSERVACIÓN primero:** `pead_tag` (SUE decaído ~30-45 días de trading, gateado
   por signo de reacción día-1) e `insider_buy` (cluster/rol, código P, ventana 90d) se persisten
   en `signal_values` con peso 0, igual que se hizo con `revenue_accel`. La activación con peso
   es una versión nueva (v11+…), calibrada en el backtester sobre el histórico que estos backfills
   crean — regla del proyecto: ninguna versión sin backtest, y desde 2026-07: 2 ventanas de
   calibración + 1 OOS.

**Prerrequisito del backtest de PEAD:** el paso de validación de vintage del §3.1 es parte del
backfill, no un opcional — el script debe emitir el informe de discrepancias AV↔Finnhub↔8-K antes
de dar el histórico por bueno.

---

## Handoff notes

- **Producido:** veredicto de factibilidad de datos (GO condicional para PEAD, GO para insider),
  con endpoints, profundidades y límites verificados contra las fuentes reales; riesgos de
  lookahead explícitos; diseño de ingesta (2 tablas, 2 providers, 1 job nuevo + 1 extensión,
  2 backfills one-shot) sin implementar.
- **Cambios respecto a docs previos:** yfinance NO sirve para histórico de earnings (corrige la
  asunción "⚠️ thin" de la síntesis §2.2 — es peor: 4 trimestres); OpenInsider deja de tener
  sentido como prototipo porque los bulk datasets de la SEC dan lo mismo estructurado; Alpha
  Vantage sube de "Limited" a fuente clave para ESTE caso de uso (el cupo de 25/día solo duele
  en pulls recurrentes, no en un backfill one-shot).
- **Para el siguiente agente:** no escribir código de señal hasta que el backfill exista y la
  validación de vintage (§3.1) haya pasado; si falla, PEAD pasa a NO-GO y solo procede insider.
- **Decisiones abiertas:** (a) umbral de discrepancia AV↔Finnhub aceptable (propuesta: <5% de
  trimestres con |Δestimate| > $0.01 → aceptar); (b) si `fetch_insider_filings` merece job propio
  o se cuelga de `fetch_fundamentals`; (c) pesos/decay del `pead_tag` — asunto del Experiment
  Tracker tras el backtest, no de este doc.

### Fuentes verificadas (agosto 2026)

- Alpha Vantage `EARNINGS` (respuesta real, key demo): [alphavantage.co/query?function=EARNINGS&symbol=IBM](https://www.alphavantage.co/query?function=EARNINGS&symbol=IBM&apikey=demo) · [docs](https://www.alphavantage.co/documentation/)
- Finnhub free = 4 trimestres de surprises: [apicostcalc.com/finnhub](https://apicostcalc.com/finnhub.html) · [docs /stock/earnings](https://finnhub.io/docs/api/company-earnings) · [docs /calendar/earnings](https://finnhub.io/docs/api/earnings-calendar)
- yfinance limitado a 4 trimestres de earnings history: [discusión oficial #2159](https://github.com/ranaroussi/yfinance/discussions/2159) · [get_earnings_dates API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_earnings_dates.html)
- SEC Insider Transactions Data Sets (bulk trimestral desde 2006): [sec.gov](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) · [readme oficial](https://www.sec.gov/files/insider_transactions_readme.pdf) · [catalog.data.gov](https://catalog.data.gov/dataset/insider-transactions-data-sets)
- EDGAR submissions API (`acceptanceDateTime`, 10 req/s, User-Agent): [sec.gov APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [guía de campos](https://fundamentalshub.com/blog/data-sec-gov-submissions-json) · [guía rate limits](https://dealcharts.org/blog/sec-edgar-api-guide)
- Nasdaq calendar API (no oficial, wrapper): [finance_calendars](https://github.com/s-kerin/finance_calendars)
- OpenInsider scraping (referencia, descartado): [openinsiderData scraper](https://github.com/sd3v/openinsiderData)
