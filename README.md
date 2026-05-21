# Autonomous Trader

Sistema autónomo de paper trading que analiza mercados diariamente, simula inversiones y expone un dashboard web para monitorizar todo. Diseñado para correr en Docker sobre una Raspberry Pi 4 (ARM64).

> **Estado actual:** Definición de arquitectura. El desarrollo se lanza con los agentes de IA descritos en este documento.

---

## Qué hace este sistema

- Descarga datos de mercado diariamente (acciones, ETFs, índices)
- Puntúa y rankea activos usando análisis técnico
- Simula operaciones en un portfolio virtual (sin dinero real)
- Expone un dashboard web con: balance, posiciones, gráficas, histórico de operaciones y estado del sistema
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

### FASE 0 — Investigación
*Secuencial. Nada más empieza hasta que esté completa.*

| Agente | Output |
|---|---|
| Investment Researcher | `docs/research/sector-study.md` — sectores, universo de activos, taxonomía de señales |

Copia el bloque **FASE 0** de `LAUNCH_PROMPT.md` en una conversación de Claude Code.

---

### FASE 1 — Fundación
*Los 3 agentes corren en paralelo. Requiere FASE 0.*

| Agente | Output |
|---|---|
| Software Architect | `docs/architecture/module-contracts.md` + protocolos Python |
| Database Optimizer | `docs/architecture/schema.md` + migraciones Alembic |
| Workflow Architect | `docs/architecture/workflow-tree.md` |

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
    def place_order(self, symbol: str, side: str, qty: int, order_type: str) -> Order: ...
    def get_positions(self) -> list[Position]: ...
    def get_account_balance(self) -> Decimal: ...
    def get_order_status(self, order_id: str) -> OrderStatus: ...
```

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

## Jobs diarios (scheduler)

```
07:00 UTC  →  fetch_market_data()       Descarga OHLCV del día
07:30 UTC  →  run_analysis()            Calcula indicadores y scores
08:00 UTC  →  execute_paper_trades()    Ejecuta operaciones simuladas
08:15 UTC  →  update_portfolio_nav()    Actualiza valor del portfolio
```

Todos los jobs son idempotentes. Si se ejecutan dos veces el mismo día, no duplican datos.

---

## Documentación adicional

- [CLAUDE.md](CLAUDE.md) — Directrices completas para agentes IA, reglas del proyecto
- [LAUNCH_PROMPT.md](LAUNCH_PROMPT.md) — Prompts listos para lanzar cada fase de desarrollo
