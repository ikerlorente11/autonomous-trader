"""API-specific response models (composed views the DB query layer doesn't return
directly). Inter-module DTOs live in ``backend.contracts``; these are dashboard
response shapes only."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class PortfolioSummary(BaseModel):
    cash: Decimal
    equity: Decimal
    total: Decimal
    starting_cash: Decimal
    total_pnl: Decimal
    unrealized_pnl: Decimal
    positions_count: int


class WatchlistEntry(BaseModel):
    symbol: str
    sector: str | None = None
    asset_class: str | None = None
    latest_price: Decimal | None = None
    score: Decimal | None = None
    action: str | None = None
    ts: dt.datetime | None = None


class SignalEntry(BaseModel):
    symbol: str
    ts: dt.datetime
    score: Decimal
    action: str
    reason: str | None = None
    indicator_snapshot: dict | None = None
    strategy_version: str | None = None


class ExperimentEntry(BaseModel):
    id: int
    strategy_version: str
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    config: dict | None = None
    notes: str | None = None


class JobStatus(BaseModel):
    job: str
    status: str | None = None
    last_run_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    next_run_at: dt.datetime | None = None


class SystemStatus(BaseModel):
    server_time: dt.datetime
    jobs: list[JobStatus]
    recent_errors: list[JobStatus]
