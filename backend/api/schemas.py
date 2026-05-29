"""API-specific response models (composed views the DB query layer doesn't return
directly). Inter-module DTOs live in ``backend.contracts``; these are dashboard
response shapes only."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

_SYMBOL_RE = re.compile(r"[A-Z0-9.\-]{1,16}")


class QuoteEntry(BaseModel):
    symbol: str
    price: Decimal


class PortfolioSummary(BaseModel):
    portfolio_id: int
    name: str
    cash: Decimal
    equity: Decimal
    total: Decimal
    contributed_capital: Decimal
    total_pnl: Decimal
    unrealized_pnl: Decimal
    positions_count: int


class Portfolio(BaseModel):
    id: int
    name: str
    active: bool
    created_at: dt.datetime


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    initial_deposit: Decimal = Field(default=Decimal(0), ge=0)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name


class PortfolioRename(BaseModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name


class CashMovementCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=256)


class CashMovement(BaseModel):
    id: int
    portfolio_id: int
    kind: str
    amount: Decimal
    ts: dt.datetime
    note: str | None = None


class WatchlistEntry(BaseModel):
    symbol: str
    sector: str | None = None
    asset_class: str | None = None
    latest_price: Decimal | None = None
    score: Decimal | None = None
    action: str | None = None
    ts: dt.datetime | None = None


class WatchlistCreate(BaseModel):
    symbol: str
    sector: str | None = Field(default=None, max_length=64)
    asset_class: str | None = Field(default=None, max_length=32)

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        symbol = value.strip().upper()
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError("symbol must be 1-16 chars of A-Z, 0-9, '.' or '-'")
        return symbol


class RunTrigger(BaseModel):
    status: str
    detail: str


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
