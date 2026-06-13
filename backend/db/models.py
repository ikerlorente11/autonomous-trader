from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

PRICE = Numeric(18, 6)
MONEY = Numeric(18, 2)
SCORE = Numeric(10, 4)


# --------------------------------------------------------------------------- #
# Time-series hypertables
# --------------------------------------------------------------------------- #
class MarketBar(Base):
    __tablename__ = "market_bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger)
    adj_close: Mapped[Decimal] = mapped_column(PRICE)


class IntradayBar(Base):
    __tablename__ = "intraday_bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger)


class SignalValue(Base):
    __tablename__ = "signal_values"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    data_completeness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))

    __table_args__ = (
        Index("ix_signal_values_symbol_signal_ts", "symbol", "signal_id", "ts"),
    )


class MacroSeries(Base):
    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    release_ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    strategy_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), server_default=text("'daily'"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_cash_movements_portfolio_ts", "portfolio_id", "ts"),
    )


class PortfolioNav(Base):
    __tablename__ = "portfolio_nav"

    portfolio_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(MONEY)
    equity: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal] = mapped_column(MONEY)
    benchmark_value: Mapped[Decimal | None] = mapped_column(MONEY)


# --------------------------------------------------------------------------- #
# Portfolio / trading
# --------------------------------------------------------------------------- #
class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    portfolio_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    avg_cost: Mapped[Decimal] = mapped_column(PRICE)
    current_price: Mapped[Decimal | None] = mapped_column(PRICE)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    # Highest price seen since entry — the reference for the intraday trailing stop.
    # Nullable: initialized lazily on the first protective-sell check (max of avg_cost
    # and the live price), so existing positions need no backfill.
    high_water_mark: Mapped[Decimal | None] = mapped_column(PRICE)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class TradeOrder(Base):
    __tablename__ = "trade_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal | None] = mapped_column(PRICE)
    commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_trade_orders_ts", text("ts DESC")),
        Index("ix_trade_orders_portfolio_ts", "portfolio_id", "ts"),
        # Partial index for the filled-order reads (cash, round-trips, idempotency guard).
        Index(
            "ix_trade_orders_filled",
            "portfolio_id",
            "ts",
            postgresql_where=text("lower(status) = 'filled'"),
        ),
    )


class AlgorithmSignal(Base):
    __tablename__ = "algorithm_signals"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    score: Mapped[Decimal] = mapped_column(SCORE)
    action: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(Text)
    indicator_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    data_completeness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    realized_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    outcome: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        Index("ix_algorithm_signals_ts_score", "ts", text("score DESC")),
    )


class Watchlist(Base):
    __tablename__ = "watchlist"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(64))
    asset_class: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    added_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(48))
    run_id: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_job_runs_job_started", "job", text("started_at DESC")),
        Index("ix_job_runs_started", text("started_at DESC")),
    )


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# Ingestion (event-driven / periodic)
# --------------------------------------------------------------------------- #
class FundamentalsQuarterly(Base):
    __tablename__ = "fundamentals_quarterly"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    period_end: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    line_items: Mapped[dict] = mapped_column(JSONB)
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class EarningsCalendar(Base):
    __tablename__ = "earnings_calendar"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    time_of_day: Mapped[str | None] = mapped_column(String(8))
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        Index("ix_earnings_calendar_report_date", "report_date"),
    )


class EarningsEstimate(Base):
    __tablename__ = "earnings_estimates"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    period_end: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sue: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AnalystEstimate(Base):
    __tablename__ = "analyst_estimates"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    mean_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    up_count: Mapped[int | None] = mapped_column(Integer)
    down_count: Mapped[int | None] = mapped_column(Integer)
    target_mean: Mapped[Decimal | None] = mapped_column(PRICE)


class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"

    accession_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    txn_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    insider_role: Mapped[str | None] = mapped_column(String(64))
    txn_type: Mapped[str | None] = mapped_column(String(16))
    shares: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    price: Mapped[Decimal | None] = mapped_column(PRICE)
    filed_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_insider_symbol_filed", "symbol", "filed_ts"),
    )


class SecFiling(Base):
    __tablename__ = "sec_filings"

    accession_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    form_type: Mapped[str] = mapped_column(String(16))
    item_codes: Mapped[list | None] = mapped_column(JSONB)
    filed_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    polarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))

    __table_args__ = (
        Index("ix_sec_filings_symbol_filed", "symbol", "filed_ts"),
    )


class NewsSentiment(Base):
    __tablename__ = "news_sentiment"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    article_count: Mapped[int] = mapped_column(Integer)
    mean_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    score_zscore: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))


class MarketSentiment(Base):
    __tablename__ = "market_sentiment"

    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    vix: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    vix_term_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    put_call: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    breadth_rsp_spy: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    fear_greed: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))


class ShortInterest(Base):
    __tablename__ = "short_interest"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    settlement_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    short_shares: Mapped[int | None] = mapped_column(BigInteger)
    days_to_cover: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
