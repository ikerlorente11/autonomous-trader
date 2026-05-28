from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ExperimentRun

_HASH_LEN = 6


def compute_strategy_version(config: dict[str, Any]) -> str:
    """Build the `{semver}+{config_hash}` identifier from a resolved config.

    The hash covers the canonicalised config so any silent weight/threshold
    change yields a distinct version even when `version:` is not bumped.
    """
    semver = str(config.get("version", "v0.0.0"))
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_HASH_LEN]
    return f"{semver}+{digest}"


class ExperimentTracker:
    """Owns experiment-run lifecycle: assign version at startup, stamp identity, finalise."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._active_version: str | None = None

    async def ensure_active_run(self, resolved_config: dict[str, Any]) -> ExperimentRun:
        """Open/reuse the run for the current config; close & finalise a superseded one.

        Called once at scheduler startup, before any job runs.
        """
        raise NotImplementedError

    def current_version(self) -> str | None:
        """Active `strategy_version` to stamp onto signals/trades. None before startup."""
        return self._active_version

    async def get_active_run(self) -> ExperimentRun | None:
        """The open run (`ended_at IS NULL`), if any."""
        stmt = select(ExperimentRun).where(ExperimentRun.ended_at.is_(None))
        return (await self._session.scalars(stmt)).one_or_none()

    async def open_run(
        self, version: str, config: dict[str, Any], notes: str | None = None
    ) -> ExperimentRun:
        """Insert a new active run with a frozen config snapshot."""
        raise NotImplementedError

    async def close_run(self, run_id: int, ended_at: dt.datetime | None = None) -> None:
        """Set `ended_at` on a run, marking it superseded."""
        raise NotImplementedError

    async def finalize_run(self, run_id: int, results: dict[str, Any]) -> None:
        """Persist the frozen `summary.json` (FP&A §5.3 shape) into `experiment_runs.results`.

        Requires the `results` JSONB column (schema request §5) — until then this is a no-op stub.
        """
        raise NotImplementedError
