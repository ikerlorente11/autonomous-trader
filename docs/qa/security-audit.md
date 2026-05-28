<!-- Agent: Security Engineer | Phase: 6 | Depends on: Phase 5 (Frontend Developer, DevOps Automator) -->

# Security Audit

Scope: full codebase (`backend/`, `frontend/`, `docker/`, `config/`, repo root).
Posture: single-user, local-network, paper-trading only — no real money, no auth by design.

## Summary

| Severity | Count | Status |
|---|---|---|
| MUST FIX | 1 | **Fixed in this pass** |
| ADVISORY | 5 | Documented (operator action / future work) |
| PASS | 13 checks | No action needed |

One concrete secret-leak bug was found and **fixed directly**. Everything else on the
checklist passes; remaining items are advisories that depend on operator deployment
choices, not code defects.

---

## 1. Secrets management

- **PASS** — No hardcoded credentials, API keys, or passwords anywhere in code or config.
  The Twelve Data key comes from `TWELVE_DATA_API_KEY`; DB creds come from `POSTGRES_*` /
  `DATABASE_URL`. Verified via repo-wide grep — only env reads, no literals.
- **PASS** — `.env.example` contains placeholders only (`change_me_strong_password`,
  empty `TWELVE_DATA_API_KEY`). No real secrets.
- **PASS** — `.gitignore` ignores `.env` and `.env.*` with a `!.env.example` exception.
  `git ls-files` confirms **no** `.env` or secret file is tracked.
- **PASS** — `docker-compose.yml` injects secrets via `env_file: ../.env` only. No secrets
  passed as build args (build args bake into image layers; none are used here).
- **ADVISORY (operator)** — The placeholder DB password `change_me_strong_password` appears
  twice in `.env.example` (as `POSTGRES_PASSWORD` and embedded in `DATABASE_URL`). The
  operator MUST set a strong password in both places in the real `.env` before deployment.
  Documented in `.env.example` already; reiterated here.

## 2. API security

- **PASS — CORS** — `backend/api/main.py` adds `CORSMiddleware` only when
  `CORS_ALLOW_ORIGINS` is non-empty; default is empty → same-origin only (the API serves the
  dashboard itself). Methods restricted to `GET`; credentials not enabled. Correct for a
  local-only read-only dashboard.
- **PASS — Input validation** — All endpoints use FastAPI typed params and Pydantic response
  models (`backend/api/schemas.py`, `backend/contracts.py`). Numeric limits are bounded
  (`limit: int = Query(default=50, ge=1, le=500)`; algorithms `ge=1, le=200`). Datetimes are
  parsed/validated by FastAPI. `symbol` is a free string but only ever flows into
  parameterized queries (see below) and `encodeURIComponent`-escaped on the client.
- **PASS — SQL injection** — Every query in `backend/db/queries/*` uses the SQLAlchemy
  Core/ORM expression API with bound parameters (`==`, `.in_()`, `func.*`). No f-string or
  `%`-formatted SQL. `text()` occurrences are all **static** (column defaults like
  `text("now()")`, index DDL like `text("ts DESC")`) with zero user input. Migrations use
  static `op.execute()` DDL. Config uses `yaml.safe_load` (no arbitrary-object
  deserialization). No injection surface found.
- **PASS — Auth** — None, which the checklist explicitly permits for a single-user,
  local-only tool. The API is read-only (the scheduler is the only writer), shrinking the
  attack surface further.
- **ADVISORY — Rate limiting / bind address** — There is no rate limiting, and `api` binds
  `0.0.0.0:8000` and publishes `8000:8000`, so the dashboard is reachable from the **entire
  LAN**, not just localhost. Acceptable per the "local network" scope, but if the Pi shares a
  network with untrusted devices, the operator should restrict exposure — e.g. publish
  `127.0.0.1:8000:8000` (single-machine access) or front it with a firewall rule. No code
  change required; deployment choice.

## 3. Docker security

- **PASS — Non-root** — `docker/Dockerfile` creates `appuser` (uid 10001) and sets
  `USER appuser`; `api`, `scheduler`, and `init` all run from this image as non-root. The
  `db` service uses the official TimescaleDB image (runs as the internal `postgres` user).
- **PASS — No privileged containers** — No `privileged`, `cap_add`, or host namespace
  settings in `docker-compose.yml`.
- **PASS — Port exposure** — Only `api` publishes a port (`8000:8000`). The `db` service's
  `ports:` block is commented out → **5432 is not exposed to the host**. `scheduler` and
  `init` expose nothing.
- **PASS — Build context hygiene** — `.dockerignore` excludes `.env`, `.git`, caches,
  `node_modules`, and `frontend/build`, keeping secrets and cruft out of the build context.

## 4. Dependency audit

- **PASS** — All Python deps are pinned and ARM64-verified (`requirements*.txt`). Stack:
  fastapi 0.115.5, uvicorn 0.32.1, pydantic 2.10.3, starlette (transitive, ≥0.40 via
  fastapi — past the known multipart-DoS fix), SQLAlchemy 2.0.36, asyncpg 0.30.0,
  psycopg 3.2.3, httpx 0.28.1, APScheduler 3.10.4, pandas 2.2.3, numpy 2.1.3, yfinance 0.2.50.
  No known critical CVEs at these versions as of the audit date.
- **ADVISORY** — Run `pip-audit` (and `npm audit` for the frontend) in CI to catch future
  CVE disclosures against these pins; this audit is a point-in-time check.
- **ADVISORY (maintenance, not security)** — `yfinance` is community-maintained and scrapes
  Yahoo's unofficial endpoints; it can break without notice. This is a data-availability
  risk, not a vulnerability — the Twelve Data fallback exists for exactly this reason.

## 5. Data handling

- **PASS** — Paper trading only; no real broker credentials stored or referenced anywhere.
  The `BrokerAdapter` seam ships `paper` only (`broker_factory.py`).
- **MUST FIX → FIXED — Twelve Data API key leaked through exceptions.**
  In `backend/data_ingestion/providers/twelve_data_provider.py`, `resp.raise_for_status()`
  sat *outside* the `try/except`, so an HTTP error response raised `httpx.HTTPStatusError`
  whose message embeds the full request URL — including `apikey=<SECRET>` in the query
  string. That exception propagated uncaught through `ingest.fetch_with_fallback` into
  `scheduler/jobs._job_context`, where it was (a) logged via `logger.exception`, (b) stored
  verbatim as `job_runs.error`, and (c) **served back to the browser** through
  `/api/system/status` (`recent_errors[].error`). Net effect: a single 4xx/5xx from Twelve
  Data would expose the live API key in logs, the DB, and an unauthenticated API response.
  **Fix applied:** added a `_redact(text, key)` helper, moved `raise_for_status()` (and the
  429 branch) inside the `try`, and re-raise as a `ProviderError` with the key scrubbed,
  using `raise ... from None` so the apikey-bearing original is not re-surfaced through the
  chained traceback. `RateLimitError` is raised before `raise_for_status` and is not an
  `httpx.HTTPError`, so it is unaffected. Verified the module compiles.
- **ADVISORY — Key in URL query string vs. DEBUG logs.** Twelve Data authenticates via the
  `apikey` **query parameter** (its standard auth mechanism), so the key necessarily appears
  in the request URL. `httpx` logs full request URLs at **DEBUG** level. If an operator sets
  `LOG_LEVEL=DEBUG`, the key could still surface in `httpx`'s own logs (independent of the
  fix above). Recommendation: keep `LOG_LEVEL` at `INFO` or higher in production (the default
  in `.env.example` is `INFO`), or pin the `httpx` logger to `WARNING` if DEBUG is ever
  needed for app code. Not fixed in code to avoid surprising global logger mutation; flagged
  for operator awareness.

---

## Handoff notes for Reality Checker

**What I produced**
- This audit (`docs/qa/security-audit.md`).
- One code fix: redacted the Twelve Data API key from all error paths in
  `backend/data_ingestion/providers/twelve_data_provider.py` (compile-verified).

**Remaining blockers:** none. No MUST FIX items are outstanding.

**Operator action items before "production" (none block `docker compose up`):**
1. Set a strong `POSTGRES_PASSWORD` in `.env` (and the matching `DATABASE_URL`) — do not ship
   the `change_me_strong_password` placeholder.
2. Keep `LOG_LEVEL=INFO` (or higher) so the Twelve Data key cannot reach `httpx` DEBUG logs.
3. If the Pi shares a LAN with untrusted devices, restrict the published port (e.g.
   `127.0.0.1:8000:8000`) or firewall it — the API has no auth by design.

**For your checklist specifically:**
- "No real API keys committed in any file" — **confirmed**, none tracked.
- "`.env.example` contains only placeholder values" — **confirmed**.
- DB port 5432 not exposed, containers non-root, only 8000 published — **confirmed**.
- These are deployment/operator notes, not code defects, so they do not gate the build.
