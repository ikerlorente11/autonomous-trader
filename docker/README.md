<!-- Agent: DevOps Automator | Phase: 5 | Depends on: workflow-tree, backend, frontend -->

# Deployment — Autonomous Trader on a Raspberry Pi 4 (ARM64)

Three services, one image, the database, and a one-shot migration job — all on a
Pi 4 (4 GB RAM). The API serves both the JSON endpoints and the built SvelteKit
dashboard from a single container (no Nginx). Services talk only through the DB.

```
db (TimescaleDB) ──┐
                   ├─► init (alembic upgrade head, runs once) ──► api  (:8000, dashboard + API)
                   └────────────────────────────────────────────► scheduler (APScheduler jobs)
```

---

## 1. Prepare the Raspberry Pi

Use **64-bit Raspberry Pi OS** (ARM64 is mandatory — all images are ARM64).

```bash
# Verify 64-bit
uname -m            # must print: aarch64

# Install Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"        # then log out / back in
docker compose version                 # confirm the compose plugin is present
```

## 2. Get the code and configure

```bash
git clone <your-repo-url> autonomous-trader
cd autonomous-trader

cp .env.example .env
nano .env            # set POSTGRES_PASSWORD and make DATABASE_URL match it
```

Minimum you must edit in `.env`:
- `POSTGRES_PASSWORD` — a strong password.
- `DATABASE_URL` — same user/password/db as the `POSTGRES_*` values, host `db`,
  driver `+asyncpg`.
- `TWELVE_DATA_API_KEY` — optional; only needed if you want the OHLCV fallback.

## 3. Build and start

```bash
# Run from the repo root so the build context (..) and .env resolve.
docker compose -f docker/docker-compose.yml up -d --build
```

First start sequence: `db` becomes healthy → `init` runs `alembic upgrade head`
(creates tables + TimescaleDB hypertables) and exits → `api` and `scheduler`
start. The build cross-compiles nothing — it builds natively on the Pi, so the
first build is slow (asyncpg/psycopg wheels). Subsequent builds are cached.

## 4. Use it

- Dashboard + API: `http://<pi-ip>:8000`
- Health check: `http://<pi-ip>:8000/api/health` → `{"status":"ok"}`
- API docs: `http://<pi-ip>:8000/docs`

## 5. Operate

```bash
docker compose -f docker/docker-compose.yml ps               # service status
docker compose -f docker/docker-compose.yml logs -f api      # API logs
docker compose -f docker/docker-compose.yml logs -f scheduler# job logs (JSON lines)
docker stats                                                 # live RAM/CPU
docker compose -f docker/docker-compose.yml down             # stop (keeps data)
docker compose -f docker/docker-compose.yml down -v          # stop + DELETE the DB volume
```

Re-running `up -d` re-runs `init` (alembic is idempotent — a no-op at head) and
restarts services. The scheduler's PostgreSQL job store survives reboots, so the
daily schedule resumes automatically (see workflow-tree §5).

---

## Handoff notes — for the Reality Checker

### What I produced
| File | Purpose |
|---|---|
| `docker/Dockerfile` | Multi-stage: node:20-alpine builds the frontend → python:3.12-slim runtime. Non-root, lean final layer. |
| `docker/docker-compose.yml` | `db`, one-shot `init`, `api`, `scheduler`. Health gates, mem_limits, named volume. |
| `docker/init-db.sh` | Waits for DB, runs `alembic upgrade head`, then seeds the watchlist from `WATCHLIST_SEED_FILE` only if the table is empty. Idempotent. |
| `docker/README.md` | This file — fresh-Pi setup + ops. |
| `.env.example` | Every env var the backend reads, grouped, placeholders only. |
| `.dockerignore` | Keeps the build context lean. |
| `backend/requirements.txt` | Consolidated, pinned, deduped; `-r` includes the four layer files. |

### Divergences from the launch prompt (deliberate, justified)
1. **WORKDIR is `/app`, not `/app/backend`; entrypoints are
   `backend.api.main:app` and `backend.scheduler.main`.** The code uses absolute
   imports (`from backend.api.routers import ...`, `from backend.scheduler.jobs
   import ...`), so `backend` must be a top-level package on `sys.path`. The
   `parents[2]` path math in `backend/api/main.py` and `backend/analysis/config.py`
   resolves to `/app` from `/app/backend/...`, which is exactly where
   `frontend/build` and `config/strategy.yaml` are placed. The launch prompt's
   `WORKDIR /app/backend` + `api.main:app` would `ImportError` immediately.
2. **Default watchlist seed (owner-approved).** Symbols are never hardcoded in
   analysis logic (CLAUDE.md); they live as data in `WATCHLIST_SEED_FILE`
   (default `config/watchlist.seed.csv`) and `init-db.sh` loads them only when
   the watchlist table is empty, so removed symbols are not resurrected. They
   stay editable via the API. Set `WATCHLIST_SEED_FILE` empty to disable.

### Alembic / driver decision
- Alembic's `env.py` uses `async_engine_from_config` + `asyncio.run(...)` and
  reads `DATABASE_URL` directly — i.e. **migrations run on the SAME async
  (`+asyncpg`) URL as the app.** No separate `ALEMBIC_DATABASE_URL` and no sync
  URL rewrite are needed for migrations. `init-db.sh` runs
  `alembic -c backend/db/migrations/alembic.ini upgrade head` from `/app`
  (`prepend_sys_path=../../..` → `/app`, so `backend.*` imports in `env.py` resolve).
- The **only** sync driver consumer is the APScheduler job store
  (`scheduler/main.py`), which rewrites `+asyncpg` → `+psycopg` itself.
  `psycopg[binary]` is in the deps, so this works with the single `DATABASE_URL`.
  `SCHEDULER_DB_URL` is an optional override, documented but unset by default.

### Migrations run exactly once
A dedicated one-shot `init` service runs `init-db.sh`; `api` and `scheduler`
gate on `condition: service_completed_successfully`. Neither long-running service
runs migrations, so there's no race. Re-running `up` re-runs `init` idempotently.

### RAM budget (CLAUDE.md target: idle < 820 MB, peak < 1.2 GB)
`mem_limit` set per service: `db` 512m, `api` 320m, `scheduler` 512m, `init`
256m (exits). These are ceilings, not reservations — idle usage should sit well
under them (TimescaleDB tuned via `TS_TUNE_MEMORY=512MB`/`NUM_CPUS=2`). The
`init` container exits before steady state, so it doesn't count toward idle.
Steady-state ceiling sum (db+api+scheduler = 1344m) exceeds the budget as a
*limit*, but the CLAUDE.md numbers are *actual idle* targets; verify with
`docker stats` on the Pi and tighten limits if real idle is comfortably lower.

### Reality Checker checklist mapping
- `docker compose up` starts 3 services cleanly on ARM64 → compose + all-ARM64
  base images (`timescale/timescaledb:latest-pg16`, `python:3.12-slim`,
  `node:20-alpine`, all named ARM64-verified in CLAUDE.md).
- TimescaleDB hypertables created on first startup → `init` runs `alembic
  upgrade head` (hypertable creation lives in the migration scripts).
- Scheduler runs the 4 daily jobs → `scheduler` service runs `backend.scheduler.main`
  with the PostgreSQL job store reachable after the `db` health gate.
- API returns valid JSON → `api` runs uvicorn; `/api/health` health-checked.
- Frontend loads + renders a chart → Stage 1 builds `frontend/build`, copied to
  `/app/frontend/build`; FastAPI mounts it at `/`.
- BrokerAdapter swap via env only → `BROKER_ADAPTER` in `.env`, no code path
  baked into the image (default `paper`). `paper` and `mock_real` are both
  registered in `broker_factory._REGISTRY`, so `BROKER_ADAPTER=mock_real` swaps
  with zero code changes; a real broker adapter is Phase 2.
- Idle RAM < 820 MB → `mem_limit`s + TS tuning set; needs `docker stats`
  verification on hardware.
- No real keys committed / `.env.example` placeholders only → `.env` is
  gitignored; `.env.example` ships placeholders only; `.dockerignore` excludes
  `.env*` (except the example) from the build context.
- Analysis/scoring modules remain stubs → untouched by DevOps.

### Open questions / things to verify on hardware
- `frontend/.npmrc` is COPYed before `npm ci`; verified it holds only
  `engine-strict=false` / `save-exact=false` (no private registry auth), so a
  clean Pi build won't need credentials.
- `PYTHONUNBUFFERED=1` is set (workflow-tree §6 requires unbuffered JSON logs to
  stdout for the health panel) — confirmed in the Dockerfile ENV.
- `npm ci` requires `frontend/package-lock.json` (present, untracked at handoff —
  ensure it's committed before the Reality Checker builds).
- Tighten `mem_limit`s after measuring real idle on the Pi if the budget is tight.
