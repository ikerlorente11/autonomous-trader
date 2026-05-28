# syntax=docker/dockerfile:1
# Multi-stage build for the autonomous-trader api + scheduler container.
# Build context is the repo ROOT (see docker-compose: context: ..). One image
# runs both services; docker-compose overrides CMD per service.
#
# Layout inside the image (load-bearing — backend/api/main.py and
# analysis/config.py resolve paths via Path(__file__).parents[2] == /app):
#   /app/backend/...        Python package (imported as `backend.*`)
#   /app/frontend/build/... SvelteKit static build (served by FastAPI)
#   /app/config/strategy.yaml
# WORKDIR is /app (NOT /app/backend): the code uses absolute imports like
# `from backend.api.routers import ...`, so `backend` must be a top-level package
# on sys.path. Entrypoints are `backend.api.main:app` / `backend.scheduler.main`.

# ---------- Stage 1: build the SvelteKit static site ----------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# adapter-static emits ./build (SPA fallback index.html)

# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build toolchain + libpq headers needed to build asyncpg/psycopg wheels on ARM64.
# Kept in the same RUN as the pip install and removed after, so the final layer
# stays lean (Pi 4 RAM/disk budget).
WORKDIR /app

COPY backend/requirements.txt backend/requirements-db.txt backend/requirements-data.txt \
     backend/requirements-analysis.txt backend/requirements-api.txt ./backend/

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential libpq-dev; \
    pip install --no-cache-dir -r backend/requirements.txt; \
    apt-get purge -y --auto-remove build-essential libpq-dev; \
    apt-get install -y --no-install-recommends libpq5; \
    rm -rf /var/lib/apt/lists/*

# Application code, packaged config, and the built frontend.
COPY backend/ ./backend/
COPY config/ ./config/
COPY docker/init-db.sh ./docker/init-db.sh
COPY --from=frontend /build/build ./frontend/build

RUN chmod +x ./docker/init-db.sh

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default CMD = api service. docker-compose overrides for scheduler / init.
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
