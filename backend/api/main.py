"""FastAPI application — serves the dashboard API and the built SvelteKit static
site from a single container (CLAUDE.md: no separate Nginx). Read-only, single-user,
no auth. The scheduler writes; the API serves."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from backend.api.routers import (
    algorithms,
    market,
    portfolio,
    portfolios,
    system,
    trades,
)

_FRONTEND_BUILD = Path(__file__).resolve().parents[2] / "frontend" / "build"


class SpaStaticFiles(StaticFiles):
    """Serve the SPA, but never let the browser cache the HTML entry. Hashed assets
    under /_app/immutable are content-addressed (safe to cache); index.html must be
    revalidated so a rebuild's new asset hashes are always picked up — otherwise a
    stale cached index points at chunk hashes that no longer exist and the app blanks."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Never mask a missing API route with the SPA shell — keep its 404 JSON.
            if exc.status_code != 404 or path.startswith("api/"):
                raise
            # SPA fallback: client routes (/market/MSFT, /portfolio, …) have no
            # prerendered file — serve the SvelteKit fallback so its router renders.
            response = await super().get_response("index.html", scope)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


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
    app.include_router(portfolios.router)
    app.include_router(market.router)
    app.include_router(trades.router)
    app.include_router(algorithms.router)
    app.include_router(system.router)

    if _FRONTEND_BUILD.is_dir():
        app.mount(
            "/", SpaStaticFiles(directory=str(_FRONTEND_BUILD), html=True), name="static"
        )

    return app


app = create_app()
