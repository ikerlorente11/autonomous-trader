"""Cross-module data contracts (DTOs).

These are the typed values passed *between* modules (provider -> analysis ->
trading -> api). They are deliberately separate from the SQLAlchemy ORM models in
``backend.db.models``: ORM rows are persistence-bound (sessions, lazy loading,
mutable identity), whereas these are immutable, JSON-serialisable transfer objects
the FastAPI layer can emit directly and the scheduler can pass around without an
open session. Field names/types mirror the matching DB columns 1:1 where a contract
maps to a table, so adapters can ``Model(**row.__dict__)`` without remapping.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Enums (mirror the free-string DB columns; keep DB authoritative on width)
# --------------------------------------------------------------------------- #
class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderState(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


# --------------------------------------------------------------------------- #
# Market data (maps to market_bars)
# --------------------------------------------------------------------------- #
class OHLCVBar(_Frozen):
    symbol: str
    ts: dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal


# --------------------------------------------------------------------------- #
# Analysis outputs
# --------------------------------------------------------------------------- #
class IndicatorResult(_Frozen):
    """One computed indicator for one symbol at one timestamp (-> signal_values)."""

    symbol: str
    ts: dt.datetime
    signal_id: str
    value: Decimal
    data_completeness: Decimal | None = None


class SymbolScore(_Frozen):
    """Composite score for one symbol before ranking (-> algorithm_signals)."""

    symbol: str
    ts: dt.datetime
    score: Decimal
    action: SignalAction
    reason: str | None = None
    indicator_snapshot: dict[str, float] | None = None
    data_completeness: Decimal | None = None


class RankedSymbol(_Frozen):
    """A scored symbol with its universe rank (ranker output, buy-candidate list)."""

    rank: int
    score: SymbolScore


# --------------------------------------------------------------------------- #
# Trading (BrokerAdapter I/O — see backend.trading.broker_adapter)
# --------------------------------------------------------------------------- #
class Order(_Frozen):
    """A placed order (maps to trade_orders; id is DB-generated, optional pre-insert)."""

    id: int | None = None
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal | None = None
    commission: Decimal | None = None
    status: OrderState
    reason: str | None = None
    strategy_version: str | None = None
    ts: dt.datetime


class Position(_Frozen):
    """A held position (maps to portfolio_positions)."""

    symbol: str
    qty: Decimal
    avg_cost: Decimal
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    updated_at: dt.datetime | None = None


class AccountBalance(_Frozen):
    """Cash and equity snapshot from the broker."""

    cash: Decimal
    equity: Decimal
    total: Decimal


class OrderStatus(_Frozen):
    """Lifecycle state of a previously placed order."""

    order_id: str
    status: OrderState
    filled_qty: Decimal
    avg_fill_price: Decimal | None = None


# --------------------------------------------------------------------------- #
# Portfolio / reporting
# --------------------------------------------------------------------------- #
class PortfolioSnapshot(_Frozen):
    """Daily NAV snapshot (maps to portfolio_nav)."""

    ts: dt.datetime
    cash: Decimal
    equity: Decimal
    total: Decimal
    benchmark_value: Decimal | None = None


class TradeRecord(_Frozen):
    """A trade row for the dashboard trades table (view over trade_orders)."""

    id: int
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal | None = None
    status: OrderState
    reason: str | None = None
    strategy_version: str | None = None
    ts: dt.datetime


class TradeRoundTrip(_Frozen):
    """A closed FIFO round trip (entry matched to a later exit) with realized P&L."""

    symbol: str
    entry_ts: dt.datetime
    exit_ts: dt.datetime
    qty: float
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float | None = None
    holding_days: int


class PerformanceMetrics(_Frozen):
    """Headline performance bundle.

    Mirrors the ``{"returns", "risk", "trades"}`` envelope returned by
    ``backend.analysis.performance.metrics.summarize_performance`` (floats, not
    Decimal, because the metric math is float-based).
    """

    returns: dict[str, float] = Field(default_factory=dict)
    risk: dict[str, float] = Field(default_factory=dict)
    trades: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# FP&A periods & P&L attribution (reporting-structure.md §1.2–1.3). Floats, to
# match the float-based metric math in backend.analysis.performance.metrics.
# --------------------------------------------------------------------------- #
class PeriodPerformance(_Frozen):
    """One period's P&L tile (WTD/MTD/YTD/inception)."""

    period: str
    start_ts: dt.datetime | None = None
    end_ts: dt.datetime | None = None
    start_value: float
    end_value: float
    pnl: float
    return_pct: float | None = None


class SymbolAttributionItem(_Frozen):
    """One symbol's contribution to a period's P&L."""

    symbol: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    contribution_pct: float | None = None


class SectorAttributionItem(_Frozen):
    """One sector's contribution to a period's P&L (watchlist sector, read-time join)."""

    sector: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    contribution_pct: float | None = None


class AttributionReport(_Frozen):
    """P&L attribution for a period along one axis (symbol or sector)."""

    period: str
    axis: str  # 'symbol' | 'sector'
    total_pnl: float
    symbols: list[SymbolAttributionItem] = Field(default_factory=list)
    sectors: list[SectorAttributionItem] = Field(default_factory=list)
