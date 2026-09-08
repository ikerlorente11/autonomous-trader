# Autonomous Trader

Sistema autónomo de paper trading que analiza mercados diariamente, simula inversiones y expone un dashboard web para monitorizar todo. Diseñado para correr en Docker sobre una Raspberry Pi 4 (ARM64).

> **Estado actual:** backend (FastAPI + TimescaleDB), pipeline diario de ingesta, motor de análisis, backtesting, dashboard SvelteKit y despliegue Docker implementados, con CI (ruff + pytest). En fase de iteración de estrategias (`config/strategies/`) en paper trading. Solo simula: no opera con dinero real.
>
> El proyecto se ha desarrollado con ayuda de agentes de IA siguiendo las directrices de `CLAUDE.md`.

---

## Qué hace este sistema

- **Predice movimientos de mercado** usando análisis multi-factor: técnico, fundamental, macro, sentimiento, noticias y smart money combinados en un score compuesto
- Actúa por adelantado a los movimientos esperados — no reacciona al precio histórico
- Descarga y procesa diariamente datos de múltiples fuentes (OHLCV, fundamentales, macro, noticias, insiders)
- Simula operaciones en un portfolio virtual (sin dinero real)
- Expone un dashboard web con: balance, posiciones, gráficas, señales del algoritmo, estado del sistema
- Preparado para conectar un broker real en el futuro cambiando solo una variable de entorno

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Base de datos | PostgreSQL 16 + TimescaleDB |
| Scheduler | APScheduler con job store en PostgreSQL |
| Frontend | SvelteKit (build estático) + Chart.js |
| Infraestructura | Docker Compose (ARM64) |
| Datos de mercado | yfinance (primario) + Twelve Data (fallback) |

---

## Estructura del proyecto

```
autonomous-trader/
├── CLAUDE.md              ← Constitución del proyecto (directrices para agentes IA)
├── LAUNCH_PROMPT.md       ← Prompts para lanzar el desarrollo con agentes IA
├── README.md              ← Este archivo
├── docs/
│   ├── research/          ← Estudio de sectores y universo de activos
│   ├── architecture/      ← Contratos de módulos, schema, árbol de workflows
│   ├── finance/           ← Métricas de rendimiento, reporting, experimentos
│   ├── design/            ← Sistema visual y arquitectura UX
│   └── qa/                ← Checklists de calidad y auditoría de seguridad
├── backend/               ← Servicios Python (API + Scheduler)
├── frontend/              ← Dashboard SvelteKit
└── docker/                ← Dockerfile + docker-compose.yml
```

---

## Cómo ejecutar el desarrollo con agentes IA

El desarrollo de este proyecto se construye con un equipo de 17 agentes especializados del repositorio [agency-agents](https://github.com/msitarzewski/agency-agents). Cada agente tiene un rol concreto y sus outputs alimentan a los siguientes.

### 1. Instalar los agentes en Claude Code

```bash
git clone https://github.com/msitarzewski/agency-agents
cd agency-agents
./scripts/install.sh --tool claude-code
```

### 2. Abrir el proyecto en Claude Code

```bash
cd autonomous-trader
claude
```

### 3. Ejecutar fase por fase

Los prompts completos para cada agente están en [LAUNCH_PROMPT.md](LAUNCH_PROMPT.md).

---

## Fases de desarrollo

### FASE 0A — Investigación (3 streams en paralelo ⚡)
*Nada más empieza hasta que la Fase 0B (síntesis) esté completa.*

| Agente | Stream | Output |
|---|---|---|
| Investment Researcher | Técnico + Fundamental | `docs/research/01-technical-fundamental.md` |
| Trend Researcher | Noticias + Sentimiento + Smart Money | `docs/research/02-news-sentiment-smartmoney.md` |
| Financial Analyst | Macro + Intermercado + Calendario | `docs/research/03-macro-intermarket-calendar.md` |

Abre **3 conversaciones simultáneas** y pega un stream en cada una.

### FASE 0B — Síntesis
*Secuencial. Requiere los 3 outputs de 0A.*

| Agente | Output |
|---|---|
| Investment Researcher | `docs/research/00-signal-synthesis.md` — mapa de prioridad de señales, fuentes de datos, arquitectura del score compuesto, modelo de régimen macro |

Este documento es la **fuente única de verdad** que leen todos los agentes de Fase 1 en adelante.

---

### FASE 1 — Fundación
*Los 3 agentes corren en paralelo. Requiere FASE 0B.*

| Agente | Output |
|---|---|
| Software Architect | `docs/architecture/module-contracts.md` + todos los protocolos Python (multi-categoría de señales) |
| Database Optimizer | `docs/architecture/schema.md` + migraciones Alembic (incluye tablas para fundamentales, macro, noticias, sentimiento) |
| Workflow Architect | `docs/architecture/workflow-tree.md` (incluye los 7 jobs diarios del scheduler) |

Abre **3 conversaciones simultáneas** en Claude Code y pega un bloque de FASE 1 en cada una.

---

### FASE 2 — Dominio financiero
*Los 3 agentes corren en paralelo. Puede solaparse con FASE 1.*

| Agente | Output |
|---|---|
| Financial Analyst | `docs/finance/performance-metrics.md` + funciones de métricas |
| FP&A Analyst | `docs/finance/reporting-structure.md` |
| Experiment Tracker | `docs/finance/experiment-framework.md` + skeleton de módulo |

---

### FASE 3 — Diseño
*Los 2 agentes corren en paralelo. Requiere FASE 0 y FASE 2.*

| Agente | Output |
|---|---|
| UI Designer | `docs/design/ui-system.md` + tokens CSS |
| UX Architect | `docs/design/ux-architecture.md` + skeleton de rutas SvelteKit |

---

### FASE 4 — Backend
*Secuencial. Cada agente depende del anterior.*

```
Data Engineer → Backend Architect → AI Engineer
```

| Agente | Output |
|---|---|
| Data Engineer | `backend/data_ingestion/` — pipeline de ingesta de datos |
| Backend Architect | `backend/api/`, `backend/trading/`, `backend/scheduler/` |
| AI Engineer | `backend/analysis/` — motor de análisis y scoring |

---

### FASE 5 — Frontend e Infraestructura
*Los 2 agentes corren en paralelo. Requiere FASES 3 y 4.*

| Agente | Output |
|---|---|
| Frontend Developer | `frontend/` — dashboard SvelteKit completo |
| DevOps Automator | `docker/` — Dockerfile multi-stage + docker-compose.yml |

---

### FASE 6 — Control de calidad
*Secuencial. Gate final antes de declarar el sistema listo.*

```
Analytics Reporter → Security Engineer → Reality Checker
```

| Agente | Output |
|---|---|
| Analytics Reporter | `docs/qa/analytics-checklist.md` |
| Security Engineer | `docs/qa/security-audit.md` + fixes aplicados |
| Reality Checker | Informe PASS/FAIL final |

---

## Reglas críticas de arquitectura

### El BrokerAdapter (regla sagrada)

Todo el sistema de trading pasa por este protocolo. Cambiar de paper trading a broker real = cambiar una variable de entorno, sin tocar código.

```python
class BrokerAdapter(Protocol):
    def place_order(self, symbol: str, side: str, qty: Decimal, order_type: str) -> Order: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_balance(self) -> Decimal: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
```

> `qty` es `Decimal` (no `int`) para soportar **acciones fraccionadas**: así un presupuesto pequeño puede invertir en valores de precio alto.

### Lo que está intencionalmente vacío

Los siguientes módulos tienen interfaces definidas pero sin lógica de negocio. Se rellenan tras el estudio de sectores (FASE 0):

- `backend/analysis/indicators/` — qué indicadores usar
- `backend/analysis/scoring/` — cómo ponderar y rankear señales
- `backend/trading/risk_manager.py` — reglas de position sizing
- Tabla `watchlist` — qué símbolos seguir

### Budget de RAM (Raspberry Pi 4, 4GB)

| Servicio | RAM idle objetivo |
|---|---|
| TimescaleDB | < 200 MB |
| API (FastAPI) | < 120 MB |
| Scheduler | < 100 MB |
| OS + Docker | ~400 MB |
| **Total idle** | **< 820 MB** |

---

## Configuración rápida (cuando el código esté generado)

```bash
# 1. Clonar y configurar
git clone git@github.com:ikerlorente11/autonomous-trader.git
cd autonomous-trader
cp .env.example .env
# Editar .env con tus valores

# 2. Arrancar
docker compose up -d

# 3. Ver logs
docker compose logs -f

# 4. Acceder al dashboard
# http://[IP-de-la-Pi]:8000
```

---

## Desarrollo (hot reload)

Para no reconstruir la imagen en cada cambio, usa el override de desarrollo:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up
```

- Abre el dashboard de **desarrollo** en **http://localhost:5173** (no el :8080 de producción).
- **Frontend:** Vite con **HMR** — editas algo en `frontend/` y el navegador se actualiza al instante.
- **Backend:** el código va montado y `uvicorn --reload` recarga solo al cambiar Python; la API sigue en `:8080`.
- La **imagen solo se reconstruye para producción** (`docker compose -f docker/docker-compose.yml up -d`,
  que hornea el build estático de SvelteKit servido por FastAPI).

> Alternativa sin Docker para el front: con la API levantada, `cd frontend && npm install && npm run dev`
> (Vite proxyea `/api` a `http://localhost:8080`).

---

## Uso del dashboard

### Carteras (multi-portfolio)

- El sistema arranca con **dos carteras**: `Cartera 500` (500 €) y `Cartera 100K` (100 000 €).
  Puedes **crear o borrar** más desde la página **Portfolios**.
- El **selector** de la barra superior cambia la cartera activa al instante (recarga la vista,
  como cambiar de proyecto). Cada cartera tiene sus propias posiciones, operaciones y NAV.
- Los presupuestos son **editables**: usa **Deposit / Withdraw** en la página Portfolios para
  simular ingresos o retiradas. El rendimiento (% de subida/bajada) se mide contra el
  **capital aportado neto** (depósitos − retiradas), no contra una cifra inicial fija.
- El motor diario y **Run now** operan **todas las carteras activas**, cada una dimensionada
  según su propio efectivo.

### Acciones fraccionadas

- Con `ALLOW_FRACTIONAL=true` (por defecto) el sistema compra **fracciones de acción**, así
  cualquier presupuesto puede tomar posición incluso en valores caros. `MIN_POSITION_EUR`
  descarta posiciones por debajo de ese importe (suelo anti-polvo).
- `STARTING_CASH` ya **no** define el dinero de la cartera de paper trading: los presupuestos
  reales viven en los movimientos de caja de cada cartera (sembrados por la migración y
  editables después).

### Poblar la watchlist (necesario para que opere)

El sistema solo invierte en los símbolos de la watchlist; **arranca vacía**. Añádelos desde
la página **Market** (campo "Add symbol") o por API:

```bash
curl -X POST http://[IP-de-la-Pi]:8000/api/market/watchlist \
  -H 'Content-Type: application/json' -d '{"symbol":"AAPL"}'
```

### Lanzar las operaciones a mano

El pipeline corre solo a diario (ver más abajo), pero el botón **Run now** del dashboard
(Home) ejecuta la secuencia completa al instante: datos de mercado → análisis → trades →
snapshot de NAV. Es idempotente: repetirlo el mismo día no duplica operaciones.

### Pantalla principal (Home)

Muestra los datos vitales: presupuesto inicial, valor actual, cambio en % vs. el inicio, la
gráfica del valor en el tiempo, y la tabla de **inversiones** del día (con selector de fecha).
Cada fila abre la gráfica de tendencia del valor en el que se invirtió.

---

## Jobs diarios (scheduler)

```
06:00 UTC  →  fetch_macro_data()        FRED API: tipos de interés, inflación, indicadores líderes
06:15 UTC  →  fetch_news_sentiment()    NewsAPI + Fear & Greed Index
06:30 UTC  →  fetch_market_data()       OHLCV bars (yfinance primario)
06:45 UTC  →  fetch_fundamentals()      Earnings, revisiones de analistas, insiders (Form 4)
07:30 UTC  →  run_analysis()            Todas las categorías de señales → score compuesto
08:00 UTC  →  execute_paper_trades()    Señales top-ranked → órdenes simuladas
08:15 UTC  →  update_portfolio_nav()    Snapshot del valor del portfolio
```

Los jobs de ingesta (06:xx) corren en secuencia. El análisis (07:30) lee de la DB, nunca llama APIs directamente. Todos los jobs son idempotentes.

---

## Documentación adicional

- [CLAUDE.md](CLAUDE.md) — Directrices completas para agentes IA, reglas del proyecto
- [LAUNCH_PROMPT.md](LAUNCH_PROMPT.md) — Prompts listos para lanzar cada fase de desarrollo

## Licencia

Puedes usar, modificar y compartir este proyecto libremente para fines **no comerciales**.
No está permitido venderlo ni ganar dinero con él. Ver [LICENSE](LICENSE) (PolyForm Noncommercial 1.0.0).
