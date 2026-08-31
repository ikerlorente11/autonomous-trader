"""API-specific response models (composed views the DB query layer doesn't return
directly). Inter-module DTOs live in ``backend.contracts``; these are dashboard
response shapes only."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

_SYMBOL_RE = re.compile(r"[A-Z0-9.\-]{1,16}")
# Upper bound on a single cash movement / initial budget — guards against a typo or
# abuse injecting an absurd Decimal into NAV / contributed-capital math.
_MAX_CASH = Decimal("1e12")


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
    strategy_label: str | None = None
    kind: str = "daily"
    created_at: dt.datetime


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    initial_deposit: Decimal = Field(default=Decimal(0), ge=0, le=_MAX_CASH)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name


class PortfolioUpdate(BaseModel):
    """Partial update: only the fields present in the request are applied. ``name``
    renames; ``strategy_label`` sets the strategy version (null = base config);
    ``active`` retires or revives the book without deleting its history."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    strategy_label: str | None = Field(default=None, max_length=16)
    active: bool | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("name must not be blank")
        return name

    @field_validator("strategy_label")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        label = value.strip()
        return label or None


class StrategyVersion(BaseModel):
    label: str
    strategy_version: str


class PortfolioCosts(BaseModel):
    """Cost attribution: how much of a portfolio's P&L is trading friction.
    ``slippage_est`` derives from the CURRENT ``SLIPPAGE_PCT`` (fills embed slippage;
    the pre-slippage price isn't stored), so it is an estimate, not a ledger."""

    portfolio_id: int
    fills: int
    buys: int
    sells: int
    buy_notional: Decimal
    sell_notional: Decimal
    realized_flow: Decimal
    commission_total: Decimal
    slippage_est: Decimal


class CashMovementCreate(BaseModel):
    amount: Decimal = Field(gt=0, le=_MAX_CASH)
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


class SignalAccuracySummary(BaseModel):
    accuracy: float | None = None
    signal_count: int
    correct_count: int


class ExperimentEntry(BaseModel):
    id: int
    strategy_version: str
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    config: dict | None = None
    notes: str | None = None


class PortfolioStatsView(BaseModel):
    portfolio_id: int
    name: str
    strategy_label: str | None = None
    n_days: int
    total_return: float | None = None
    cagr: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    pnl_pct: float | None = None
    final_nav: float | None = None
    contributed: float


class SignificanceView(BaseModel):
    p_value: float | None = None
    statistic: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    significant: bool


class PortfolioComparisonView(BaseModel):
    a: PortfolioStatsView
    b: PortfolioStatsView
    paired_days: int
    returns_significance: SignificanceView
    sharpe_significance: SignificanceView
    verdict: str
    notes: list[str] = Field(default_factory=list)


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
    micro_enabled: bool = False
