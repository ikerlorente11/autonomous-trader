"""FastAPI application — serves the dashboard API and the built SvelteKit static
site from a single container (CLAUDE.md: no separate Nginx). Read-only, single-user,
no auth. The scheduler writes; the API serves."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routers import algorithms, market, portfolio, system, trades

_FRONTEND_BUILD = Path(__file__).resolve().parents[2] / "frontend" / "build"


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="Autonomous Trader API", version="1.0")

    origins = _cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(portfolio.router)
    app.include_router(market.router)
    app.include_router(trades.router)
    app.include_router(algorithms.router)
    app.include_router(system.router)

    if _FRONTEND_BUILD.is_dir():
        app.mount(
            "/", StaticFiles(directory=str(_FRONTEND_BUILD), html=True), name="static"
        )

    return app


app = create_app()
